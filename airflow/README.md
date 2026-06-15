# Airflow / Cloud Composer — batch analytics pipeline

This folder holds the Airflow DAG that orchestrates the **batch / warehouse**
side of the project. It is intentionally separate from the n8n workflow:

| Path | Owner | Trigger | Output |
|------|-------|---------|--------|
| **A — real-time report** | n8n + Flask (`server.py`) | new PDF in Google Drive | Excel report → Drive / Telegram / Email |
| **B — warehouse analytics** | **this Airflow DAG** | schedule (or manual) | `raw` → dbt models in the `analytics` dataset |

Both paths call the same parser core (`Bank_Statement_Analyser`) and the same
category seed (`dbt_bank/seeds/category_keywords.csv`), so categories stay
consistent across the Excel report and BigQuery.

## DAG: `bank_statement_pipeline`

```
ingest_pdf  ->  load_to_bigquery  ->  dbt_build  ->  notify
```

1. **ingest_pdf** — resolves the statement PDF to a local path. Uses
   `dag_run.conf["pdf_path"]` if given (local path or `gs://…`), otherwise
   discovers the newest PDF under the configured GCS prefix.
2. **load_to_bigquery** — runs `load_to_bigquery.py` to append parsed rows into
   `raw.bank_transactions` (append-only load job).
3. **dbt_build** — runs `dbt build` (seeds + models + tests). `fct_transactions`
   is incremental, so only the newly loaded transactions are appended.
4. **notify** — placeholder for downstream signalling (Slack / email / n8n
   webhook). No-op by default.

## Configuration

Set these as **Airflow Variables** (preferred) or environment variables; the DAG
falls back to env vars so it behaves like the CLI:

| Variable | Env var | Notes |
|----------|---------|-------|
| `gcp_project` | `GCP_PROJECT` | BigQuery project |
| `bq_location` | `BQ_LOCATION` | e.g. `asia-south1`; must match the `raw` dataset |
| `repo_dir` | `REPO_DIR` | path to this checkout |
| `dbt_project_dir` | `DBT_PROJECT_DIR` | defaults to `<repo_dir>/dbt_bank` |
| `python_executable` | `PYTHON_EXECUTABLE` | interpreter for the loader (needs `google-cloud-bigquery`, `pdfplumber`, `openpyxl`) |
| `dbt_executable` | `DBT_EXECUTABLE` | dbt binary (the dbt-bigquery venv) |
| `statements_gcs_bucket` | `STATEMENTS_GCS_BUCKET` | where new PDFs land (Composer) |
| `statements_gcs_prefix` | `STATEMENTS_GCS_PREFIX` | default `statements/` |

Auth: Application Default Credentials. Locally, `gcloud auth application-default
login`; on Cloud Composer, the environment's service account (grant it BigQuery
Data Editor + Job User, and Storage Object Viewer on the statements bucket).

## Running it

**Cloud Composer**
1. Upload `dags/bank_statement_pipeline.py` to the environment's `dags/` GCS folder.
2. Make the repo + a dbt-bigquery install available to workers (e.g. sync the
   repo to `gcs/data/` and install `dbt-bigquery` via a PyPI package or a custom
   image), then point `repo_dir` / `dbt_executable` at them.
3. Set the Variables above. The `@daily` schedule then discovers and processes
   new PDFs from the GCS prefix.

**Local Airflow (quick test)**
```bash
export GCP_PROJECT=n8n-upi-tracker BQ_LOCATION=asia-south1
export REPO_DIR=/path/to/Bank-Statement-Analyser
export PYTHON_EXECUTABLE=python DBT_EXECUTABLE=dbt
export AIRFLOW__CORE__DAGS_FOLDER="$REPO_DIR/airflow/dags"
airflow standalone
# then trigger with: {"pdf_path": "/path/to/statement.pdf"}
```

> Windows note: the loader runs on Python 3.14 and dbt in a 3.12 venv. Airflow
> itself does not run natively on Windows — use WSL2, Docker, or Cloud Composer.
> Point `python_executable` / `dbt_executable` at the right interpreters.
