"""
Ask-your-statement: an agentic text-to-SQL assistant over the BigQuery marts.

You ask a plain-English question ("how much did I spend on food in March?"); the
model is given ONE tool — run a read-only SQL query — and runs the agent loop: it
writes a BigQuery SELECT, the tool executes it (behind a read-only safety wall),
the model reads the rows, and answers in plain English.

Works on either provider, chosen by whichever key is set (see ai/llm.py):
    ANTHROPIC_API_KEY  -> Claude (paid)        GEMINI_API_KEY -> Gemini (free tier)

Safety wall (same for both providers): read-only (SELECT/WITH only; DML/DDL
rejected), scoped to the `analytics` dataset, and capped by maximum_bytes_billed.

Run:
    set ANTHROPIC_API_KEY  (or GEMINI_API_KEY), GCP_PROJECT, BQ_LOCATION
    python ai/ask_statement.py "how much did I spend on food, by month?"
"""
from __future__ import annotations

import json
import os
import re
import sys

from google.cloud import bigquery

# allow running directly (python ai/ask_statement.py) by putting the repo root on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai.llm import ANTHROPIC_MODEL, GEMINI_MODEL, NO_KEY_MESSAGE, gemini_api_key, get_provider

PROJECT  = os.environ.get("GCP_PROJECT", "n8n-upi-tracker")
LOCATION = os.environ.get("BQ_LOCATION", "asia-south1")
DATASET  = "analytics"
MAX_BYTES_BILLED = 100_000_000   # 100 MB scan cap — this workload scans KB
MAX_ROWS = 100                   # rows returned to the model per query

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
- Use the run_sql tool to fetch data; never invent numbers.
- Write read-only BigQuery Standard SQL (SELECT / WITH only). Fully-qualify every
  table. Aggregate in SQL rather than pulling raw rows when you can.
- Spending = debit_amount; income = credit_amount. Amounts are in INR.
- After you have the data, reply in plain English, lead with the number(s), and
  keep it concise. If a query is rejected or errors, read the message and fix the
  SQL rather than repeating it.""".strip()

# ── the safety wall ─────────────────────────────────────────────────────────
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|create|alter|truncate|grant|revoke|call)\b",
    re.IGNORECASE,
)
_STARTS_OK = re.compile(r"^\s*(with|select)\b", re.IGNORECASE | re.DOTALL)


def _is_read_only(sql: str) -> bool:
    stripped = sql.strip().rstrip(";")
    return bool(_STARTS_OK.match(stripped)) and not _FORBIDDEN.search(stripped)


def _references_only_analytics(sql: str) -> bool:
    refs = re.findall(r"\b(?:from|join)\s+`?([\w.\-]+)`?", sql, re.IGNORECASE)
    for ref in refs:
        if "." in ref and f".{DATASET}." not in f".{ref}.":
            return False
    return True


def run_query(query: str, client: bigquery.Client) -> dict:
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
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ── Claude path: manual tool-use loop ───────────────────────────────────────
def _ask_anthropic(question, verbose, sqls, model):
    import anthropic

    client = anthropic.Anthropic()
    bq = bigquery.Client(project=PROJECT, location=LOCATION)
    tools = [{
        "name": "run_sql",
        "description": (
            "Run a read-only BigQuery Standard SQL query (SELECT/WITH only) and "
            f"return up to {MAX_ROWS} rows as JSON."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "A SELECT query."}},
            "required": ["query"],
        },
    }]
    messages: list[dict] = [{"role": "user", "content": question}]

    for _ in range(8):
        resp = client.messages.create(
            model=model or ANTHROPIC_MODEL, max_tokens=16000, system=SYSTEM,
            tools=tools, thinking={"type": "adaptive"}, messages=messages,
        )
        if resp.stop_reason == "refusal":
            return "The request was declined by the model's safety system."
        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type == "tool_use" and block.name == "run_sql":
                    sql = block.input["query"]
                    sqls.append(sql)
                    if verbose:
                        print(f"\n[run_sql]\n{sql}\n", file=sys.stderr)
                    out = run_query(sql, bq)
                    results.append({
                        "type": "tool_result", "tool_use_id": block.id,
                        "content": json.dumps(out, default=str), "is_error": "error" in out,
                    })
            messages.append({"role": "user", "content": results})
            continue
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    return "Stopped after too many steps without a final answer."


# ── Gemini path: explicit function-calling loop (free tier, google-genai SDK) ─
def _ask_gemini(question, verbose, sqls, model):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=gemini_api_key())
    bq = bigquery.Client(project=PROJECT, location=LOCATION)

    run_sql_decl = types.FunctionDeclaration(
        name="run_sql",
        description=(
            "Run a read-only BigQuery Standard SQL query (SELECT/WITH only) against the "
            f"{PROJECT}.{DATASET} dataset and return up to {MAX_ROWS} rows as JSON."
        ),
        parameters=types.Schema(
            type="OBJECT",
            properties={"query": types.Schema(type="STRING", description="A SELECT query.")},
            required=["query"],
        ),
    )
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        tools=[types.Tool(function_declarations=[run_sql_decl])],
        # we drive the loop ourselves (so we can print the SQL and surface errors)
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = [types.Content(role="user", parts=[types.Part(text=question)])]

    for _ in range(8):
        resp = client.models.generate_content(model=model or GEMINI_MODEL, contents=contents, config=config)
        calls = resp.function_calls
        if not calls:
            return (resp.text or "").strip()
        contents.append(resp.candidates[0].content)
        for call in calls:
            query = (call.args or {}).get("query", "")
            sqls.append(query)
            if verbose:
                print(f"\n[run_sql]\n{query}\n", file=sys.stderr)
            out = run_query(query, bq)
            if verbose and "error" in out:
                print(f"[run_sql error] {out['error']}", file=sys.stderr)
            contents.append(types.Content(role="user", parts=[
                types.Part.from_function_response(name=call.name, response={"result": json.dumps(out, default=str)})
            ]))
    return "Stopped after too many steps without a final answer."


def _ask_offline(question: str, pdf_path: str, model: str | None, verbose: bool) -> str:
    """Offline fallback: answer from a parsed PDF when BigQuery is unavailable.

    The question and the full in-memory analytics result are sent to the LLM
    in a single prompt — no tool-use loop, no BigQuery connection needed.
    Works on Gemini (free) or Claude.
    """
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from Bank_Statement_Analyser import (
        analyse, detect_bank, monthly_summary, category_summary,
        top_merchants, detect_anomalies, clean_and_enrich, extract_transactions,
    )
    import tempfile

    if verbose:
        print(f"[offline] Parsing {pdf_path}…", file=sys.stderr)

    bank  = detect_bank(pdf_path)
    rows  = clean_and_enrich(extract_transactions(pdf_path))
    if not rows:
        return "No transactions found in the PDF."

    dates  = [r["date"] for r in rows]
    stats  = {
        "bank":          bank,
        "period":        f"{min(dates)} to {max(dates)}",
        "transactions":  len(rows),
        "total_debit":   sum(r["debit"]  for r in rows),
        "total_credit":  sum(r["credit"] for r in rows),
        "monthly":       monthly_summary(rows),
        "categories":    category_summary(rows),
        "top_merchants": top_merchants(rows),
        "anomalies":     [
            {"date": str(r["date"]), "narration": r["narration"],
             "debit": r["debit"], "merchant": r["merchant"]}
            for r in rows if r.get("is_anomaly")
        ],
    }

    prompt = (
        f"You are a bank-statement analytics assistant. The user asked:\n\n"
        f"{question}\n\n"
        f"Here is the full analytics summary of their statement (JSON):\n\n"
        f"{json.dumps(stats, default=str, indent=2)}\n\n"
        "Answer the question in plain English using only the data above. "
        "Lead with the number(s). Keep it concise. Amounts are in INR."
    )

    provider = get_provider()
    if provider == "anthropic":
        import anthropic
        resp = anthropic.Anthropic().messages.create(
            model=model or ANTHROPIC_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    elif provider == "gemini":
        from google import genai
        client = genai.Client(api_key=gemini_api_key())
        resp = client.models.generate_content(model=model or GEMINI_MODEL, contents=prompt)
        return (resp.text or "").strip()
    raise RuntimeError(NO_KEY_MESSAGE)


def ask(
    question: str,
    verbose: bool = False,
    model: str | None = None,
    return_sql: bool = False,
    pdf_path: str | None = None,
):
    """Run the agentic loop on whichever provider has a key set.

    When BigQuery is unavailable (GCP_PROJECT not set or BQ unreachable) and
    pdf_path is provided, falls back to offline mode — answers from the parsed
    PDF without any SQL or cloud connection.

    Returns the answer string, or {"answer", "sql"} when return_sql=True.
    """
    # Offline fallback: no BQ project set but a PDF is available
    if not PROJECT and pdf_path:
        if verbose:
            print("[offline mode] GCP_PROJECT not set — answering from PDF directly.", file=sys.stderr)
        answer = _ask_offline(question, pdf_path, model, verbose)
        return {"answer": answer, "sql": []} if return_sql else answer

    provider = get_provider()
    sqls: list[str] = []
    if provider == "anthropic":
        answer = _ask_anthropic(question, verbose, sqls, model)
    elif provider == "gemini":
        answer = _ask_gemini(question, verbose, sqls, model)
    else:
        raise RuntimeError(NO_KEY_MESSAGE)
    return {"answer": answer, "sql": sqls} if return_sql else answer


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Ask a question about your bank statement.")
    parser.add_argument("question", nargs="+", help="Plain-English question")
    parser.add_argument("--pdf", help="PDF path for offline mode (when BigQuery is unavailable)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    print(ask(" ".join(args.question), verbose=args.verbose, pdf_path=args.pdf))


if __name__ == "__main__":
    main()
