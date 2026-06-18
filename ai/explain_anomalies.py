"""
Anomaly explainer: turn the flagged transactions into plain-English reasons.

The warehouse flags a transaction as an anomaly when its debit is far above the
usual spend (debit > mean + 2 * population stddev). That's a number, not an
explanation. This script reads the flagged rows plus the spend baseline, and asks
Claude to write a one-sentence, human-readable reason for each — e.g.
"₹90,000 to ACME is ~10x your ₹8,700 average spend; flagged as unusually large."

It's a batch job (input flagged rows -> output explanations), not a chatbot.
By default it prints to the screen; pass --write to also store the explanations
in `analytics.anomaly_explanations` so the dashboard can show them.

Run:
    pip install anthropic
    set ANTHROPIC_API_KEY, GCP_PROJECT, BQ_LOCATION
    python ai/explain_anomalies.py            # print only
    python ai/explain_anomalies.py --write    # also save to BigQuery
"""
from __future__ import annotations

import json
import os
import sys

import anthropic
from google.cloud import bigquery

PROJECT  = os.environ.get("GCP_PROJECT", "n8n-upi-tracker")
LOCATION = os.environ.get("BQ_LOCATION", "asia-south1")
DATASET  = "analytics"
MODEL    = "claude-opus-4-8"

ANOMALY_QUERY = f"""
with stats as (
    select avg(debit_amount) as mean_debit
    from `{PROJECT}.{DATASET}.fct_transactions`
    where debit_amount > 0
)
select
    f.transaction_id,
    f.txn_date,
    f.merchant,
    f.category,
    f.debit_amount,
    s.mean_debit
from `{PROJECT}.{DATASET}.fct_transactions` f
cross join stats s
where f.is_anomaly
order by f.debit_amount desc
"""

# Structured output: one explanation per transaction_id.
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "explanations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["transaction_id", "explanation"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["explanations"],
    "additionalProperties": False,
}


def fetch_anomalies(bq: bigquery.Client) -> list[dict]:
    return [dict(r) for r in bq.query(ANOMALY_QUERY).result()]


def explain(anomalies: list[dict]) -> list[dict]:
    """One Claude call: returns [{transaction_id, explanation}, ...]."""
    client = anthropic.Anthropic()
    payload = [
        {
            "transaction_id": a["transaction_id"],
            "merchant": a["merchant"],
            "category": a["category"],
            "debit_amount": float(a["debit_amount"]),
            "date": a["txn_date"].isoformat(),
            "average_spend": round(float(a["mean_debit"]), 2),
        }
        for a in anomalies
    ]
    prompt = (
        "These transactions were flagged as anomalies because the amount is far "
        "above the average spend. For each one, write a single plain-English "
        "sentence explaining why it stands out — name the merchant, the amount in "
        "₹, and roughly how many times the average it is. Be concrete and concise.\n\n"
        + json.dumps(payload, indent=2)
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)["explanations"]


def write_to_bigquery(explanations: list[dict], bq: bigquery.Client) -> None:
    table_id = f"{PROJECT}.{DATASET}.anomaly_explanations"
    schema = [
        bigquery.SchemaField("transaction_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("explanation", "STRING"),
    ]
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    bq.load_table_from_json(explanations, table_id, job_config=job_config).result()
    print(f"Saved {len(explanations)} explanations to {table_id}.")


def main() -> None:
    bq = bigquery.Client(project=PROJECT, location=LOCATION)
    anomalies = fetch_anomalies(bq)
    if not anomalies:
        print("No anomalies flagged.")
        return

    explanations = explain(anomalies)
    for e in explanations:
        print(f"- {e['explanation']}")

    if "--write" in sys.argv:
        write_to_bigquery(explanations, bq)


if __name__ == "__main__":
    main()
