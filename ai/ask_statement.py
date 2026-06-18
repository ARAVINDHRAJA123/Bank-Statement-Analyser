"""
Ask-your-statement: an agentic text-to-SQL assistant over the BigQuery marts.

You ask a plain-English question ("how much did I spend on food in March?");
Claude is given ONE tool — `run_sql` — and runs the agent loop itself: it writes
a BigQuery SELECT, the tool executes it (behind a read-only safety wall), Claude
reads the rows, and answers in plain English.

This is the "agentic" pattern: the model decides to act (call the tool), observes
the result, and continues until it can answer — we control the loop and gate the
single action.

Safety wall (mirrors a preview-only / no-destructive-actions design):
  * read-only — only SELECT / WITH queries run; any DML/DDL is rejected
  * scoped — queries must reference the `analytics` dataset only
  * capped — maximum_bytes_billed stops a query from ever running up a bill
  * fail-clean — a rejected or failing query returns an error to the model
    (which can correct its SQL), never an unsafe retry

Run:
    pip install anthropic
    set ANTHROPIC_API_KEY, GCP_PROJECT, BQ_LOCATION
    python ai/ask_statement.py "how much did I spend on food, by month?"
"""
from __future__ import annotations

import json
import os
import re
import sys

import anthropic
from google.cloud import bigquery

PROJECT  = os.environ.get("GCP_PROJECT", "n8n-upi-tracker")
LOCATION = os.environ.get("BQ_LOCATION", "asia-south1")
DATASET  = "analytics"
MODEL    = "claude-opus-4-8"
MAX_BYTES_BILLED = 100_000_000   # 100 MB scan cap — this workload scans KB
MAX_ROWS = 100                   # rows returned to the model per query

# Schema the model is allowed to query (the star-schema marts + aggregates).
SCHEMA_DOC = f"""
Dataset: `{PROJECT}.{DATASET}` (BigQuery Standard SQL). Always fully-qualify
tables as `{PROJECT}.{DATASET}.<table>`.

fct_transactions  -- one row per transaction (the fact table)
  transaction_id STRING, txn_date DATE, value_date DATE, merchant STRING,
  narration STRING, ref_no STRING, debit_amount NUMERIC (money out),
  credit_amount NUMERIC (money in), balance NUMERIC, category STRING,
  merchant_key STRING, category_key STRING, is_anomaly BOOL
dim_date      -- date_key DATE, year, quarter, month, month_name, month_start DATE,
                 day_of_month, day_name, day_of_week, is_weekend BOOL
dim_merchant  -- merchant_key STRING, merchant_name STRING, txn_count,
                 first_seen_date DATE, last_seen_date DATE
dim_category  -- category_key STRING, category_name STRING,
                 category_group STRING ('Income' | 'Expense')
agg_monthly_summary  -- month DATE, month_name, quarter, year, income, expense,
                        net, txn_count
agg_category_spend   -- category STRING, category_group STRING, total_amount,
                        txn_count
""".strip()

SYSTEM = f"""You are a careful analytics assistant for a personal bank-statement
warehouse in BigQuery. Answer the user's question by querying the data.

{SCHEMA_DOC}

Rules:
- Use the `run_sql` tool to fetch data; never invent numbers.
- Write read-only BigQuery Standard SQL (SELECT / WITH only). Fully-qualify every
  table. Aggregate in SQL rather than pulling raw rows when you can.
- Spending = debit_amount; income = credit_amount. Amounts are in INR (₹).
- After you have the data, reply in plain English, lead with the number(s), and
  keep it concise. If a query is rejected or errors, read the message and fix the
  SQL rather than repeating it.""".strip()

TOOLS = [{
    "name": "run_sql",
    "description": (
        "Run a read-only BigQuery Standard SQL query (SELECT/WITH only) against "
        f"the {PROJECT}.{DATASET} dataset and return up to {MAX_ROWS} rows as JSON. "
        "Use this whenever you need data to answer the question."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A BigQuery Standard SQL SELECT query. Fully-qualify tables as "
                    f"`{PROJECT}.{DATASET}.<table>`."
                ),
            }
        },
        "required": ["query"],
    },
}]

# ── the safety wall ─────────────────────────────────────────────────────────
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|create|alter|truncate|grant|revoke|call)\b",
    re.IGNORECASE,
)
_STARTS_OK = re.compile(r"^\s*(with|select)\b", re.IGNORECASE | re.DOTALL)


def _is_read_only(sql: str) -> bool:
    """A query passes only if it starts with SELECT/WITH and contains no
    data-/schema-modifying keyword."""
    stripped = sql.strip().rstrip(";")
    return bool(_STARTS_OK.match(stripped)) and not _FORBIDDEN.search(stripped)


def _references_only_analytics(sql: str) -> bool:
    """Best-effort scope check: every table after FROM/JOIN must live in the
    analytics dataset. The byte cap is the hard backstop."""
    refs = re.findall(r"\b(?:from|join)\s+`?([\w.\-]+)`?", sql, re.IGNORECASE)
    for ref in refs:
        # allow CTE names (no dots) and analytics-qualified tables only
        if "." in ref and f".{DATASET}." not in f".{ref}.":
            return False
    return True


def run_sql(query: str, client: bigquery.Client) -> dict:
    """Execute a vetted read-only query and return rows (or a clean error)."""
    if not _is_read_only(query):
        return {"error": "Rejected: only read-only SELECT/WITH queries are allowed."}
    if not _references_only_analytics(query):
        return {"error": f"Rejected: queries may only read from the {DATASET} dataset."}
    job_config = bigquery.QueryJobConfig(
        maximum_bytes_billed=MAX_BYTES_BILLED,
        use_query_cache=True,
    )
    try:
        rows = [dict(r) for r in client.query(query, job_config=job_config).result(max_results=MAX_ROWS)]
        return {"row_count": len(rows), "rows": rows}
    except Exception as e:  # surface a clean message so the model can fix its SQL
        return {"error": f"{type(e).__name__}: {e}"}


def ask(question: str, verbose: bool = False) -> str:
    """Run the agentic loop and return Claude's plain-English answer."""
    client = anthropic.Anthropic()
    bq = bigquery.Client(project=PROJECT, location=LOCATION)
    messages: list[dict] = [{"role": "user", "content": question}]

    for _ in range(8):  # hard cap on agent turns
        resp = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            tools=TOOLS,
            thinking={"type": "adaptive"},
            messages=messages,
        )

        if resp.stop_reason == "refusal":
            return "The request was declined by the model's safety system."

        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use" and block.name == "run_sql":
                    sql = block.input["query"]
                    if verbose:
                        print(f"\n[run_sql]\n{sql}\n", file=sys.stderr)
                    out = run_sql(sql, bq)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(out, default=str),
                        "is_error": "error" in out,
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        # end_turn — return the answer text
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    return "Stopped after too many steps without a final answer."


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python ai/ask_statement.py "your question"')
        sys.exit(1)
    print(ask(" ".join(sys.argv[1:]), verbose=True))


if __name__ == "__main__":
    main()
