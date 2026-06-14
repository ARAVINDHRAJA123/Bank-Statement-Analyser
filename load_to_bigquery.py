"""
Load parsed bank-statement transactions into BigQuery (raw.bank_transactions).

Reuses the PDF parsing from the analyser, but instead of writing an Excel
report it lands the raw transactions in BigQuery for dbt to model downstream.

Append-only: re-running on the same statement adds duplicate rows. That's
intentional — the dbt staging model de-duplicates, so re-runs are safe.

Usage (PowerShell):
    $env:GCP_PROJECT="your-gcp-project-id"
    $env:BQ_LOCATION="asia-south1"        # your BigQuery region (match your other datasets)
    python load_to_bigquery.py "C:\\path\\to\\statement.pdf"

Auth (do once, pick one):
    gcloud auth application-default login            # easiest for local dev
    or set GOOGLE_APPLICATION_CREDENTIALS to a service-account JSON file path
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from google.cloud import bigquery

from Bank_Statement_Analyser import extract_transactions, clean_and_enrich

PROJECT  = os.environ.get("GCP_PROJECT")
DATASET  = os.environ.get("BQ_DATASET", "raw")
TABLE    = os.environ.get("BQ_TABLE", "bank_transactions")
LOCATION = os.environ.get("BQ_LOCATION", "US")

# Raw layer holds the minimally-parsed transaction. Merchant extraction,
# categorisation and anomaly flags are derived later in dbt, not here.
SCHEMA = [
    bigquery.SchemaField("txn_date",   "DATE",      mode="REQUIRED"),
    bigquery.SchemaField("narration",  "STRING"),
    bigquery.SchemaField("ref_no",     "STRING"),
    bigquery.SchemaField("value_date", "DATE"),
    bigquery.SchemaField("debit",      "FLOAT64"),
    bigquery.SchemaField("credit",     "FLOAT64"),
    bigquery.SchemaField("balance",    "FLOAT64"),
    bigquery.SchemaField("_loaded_at", "TIMESTAMP", mode="REQUIRED"),
]


def to_bq_rows(rows: list[dict]) -> list[dict]:
    """Map the analyser's row dicts to the raw BigQuery schema."""
    loaded_at = datetime.now(timezone.utc).isoformat()
    out = []
    for r in rows:
        out.append({
            "txn_date":   r["date"].isoformat(),
            "narration":  r["narration"],
            "ref_no":     r["ref_no"] or None,
            "value_date": r["value_date"].isoformat() if r["value_date"] else None,
            "debit":      float(r["debit"]),
            "credit":     float(r["credit"]),
            "balance":    float(r["balance"]),
            "_loaded_at": loaded_at,
        })
    return out


def main():
    if not PROJECT:
        print("ERROR: set the GCP_PROJECT environment variable first.")
        sys.exit(1)

    pdf = sys.argv[1] if len(sys.argv) > 1 else "Account Statement.pdf"
    if not os.path.exists(pdf):
        print(f"ERROR: '{pdf}' not found.")
        sys.exit(1)

    print(f"[1/3] Parsing '{pdf}'…")
    rows = clean_and_enrich(extract_transactions(pdf))
    if not rows:
        print("  No transactions found. Is the PDF text-based (not scanned)?")
        sys.exit(2)
    print(f"  Parsed {len(rows)} transactions.")

    client = bigquery.Client(project=PROJECT, location=LOCATION)
    table_id = f"{PROJECT}.{DATASET}.{TABLE}"

    print(f"[2/3] Ensuring dataset '{DATASET}' exists in {LOCATION}…")
    dataset = bigquery.Dataset(f"{PROJECT}.{DATASET}")
    dataset.location = LOCATION
    client.create_dataset(dataset, exists_ok=True)

    print(f"[3/3] Loading into {table_id} (append)…")
    job_config = bigquery.LoadJobConfig(
        schema=SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    job = client.load_table_from_json(to_bq_rows(rows), table_id, job_config=job_config)
    job.result()  # wait for the load to finish

    table = client.get_table(table_id)
    print(f"\n[OK] Loaded {len(rows)} rows. {table_id} now holds {table.num_rows} rows total.")


if __name__ == "__main__":
    main()
