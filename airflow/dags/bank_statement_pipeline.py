"""
Bank Statement — batch analytics pipeline (Airflow / Cloud Composer).

This DAG owns the *batch / warehouse* side of the project (Path B):

    ingest PDF  ->  load_to_bigquery  ->  dbt build  ->  explain_anomalies  ->  notify

It is deliberately separate from the n8n workflow, which owns the *real-time*
side (Path A: Google Drive -> Flask /analyse -> Excel report -> Telegram/Email).
n8n still gives you an instant report when a statement lands; this DAG keeps the
BigQuery warehouse (raw -> staging -> marts) refreshed and tested on a schedule,
with retries, logging and backfills. The two paths share the same parser core
(Bank_Statement_Analyser) and the same category seed, so categories stay
consistent across the Excel report and the warehouse.

Configuration (Airflow Variables, with env-var fallbacks so it also runs the
same way the CLI does):

    gcp_project          -> GCP_PROJECT      (BigQuery project)
    bq_location          -> BQ_LOCATION      (e.g. asia-south1; must match raw)
    repo_dir             -> REPO_DIR         (path to the project checkout)
    dbt_project_dir      -> DBT_PROJECT_DIR  (defaults to <repo_dir>/dbt_bank)
    python_executable    -> PYTHON_EXECUTABLE (interpreter for the loader)
    dbt_executable       -> DBT_EXECUTABLE   (dbt binary, e.g. the 3.12 venv's)
    gemini_api_key       -> GEMINI_API_KEY   (free; for the anomaly-explainer step)
    anthropic_api_key    -> ANTHROPIC_API_KEY (paid alternative for the explainer)
    statements_gcs_bucket / statements_gcs_prefix
                         -> where new statement PDFs land (Cloud Composer).
                            Omit to run against a local file instead.

Trigger a single statement manually with:
    {"pdf_path": "/path/or/gs://bucket/key/statement.pdf"}
in the DAG run config; otherwise the DAG discovers the newest unprocessed PDF
under the configured GCS prefix.
"""
from __future__ import annotations

import os
import tempfile

import pendulum
from airflow import DAG
from airflow.models import Variable
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator


# ── Config helpers ──────────────────────────────────────────────────────────
def cfg(name: str, env: str, default: str | None = None) -> str | None:
    """Airflow Variable first, then env var, then default. Keeps the DAG
    runnable with the same GCP_PROJECT / BQ_LOCATION the CLI already uses."""
    return Variable.get(name, default_var=os.environ.get(env, default))


GCP_PROJECT = cfg("gcp_project", "GCP_PROJECT")
BQ_LOCATION = cfg("bq_location", "BQ_LOCATION", "US")
REPO_DIR = cfg("repo_dir", "REPO_DIR", "/home/airflow/gcs/data/Bank-Statement-Analyser")
DBT_PROJECT_DIR = cfg("dbt_project_dir", "DBT_PROJECT_DIR", os.path.join(REPO_DIR, "dbt_bank"))
PYTHON_EXECUTABLE = cfg("python_executable", "PYTHON_EXECUTABLE", "python")
DBT_EXECUTABLE = cfg("dbt_executable", "DBT_EXECUTABLE", "dbt")
GCS_BUCKET = cfg("statements_gcs_bucket", "STATEMENTS_GCS_BUCKET")
GCS_PREFIX = cfg("statements_gcs_prefix", "STATEMENTS_GCS_PREFIX", "statements/")
# Optional outbound webhook for the notify step. Works for any service that
# accepts a JSON POST: an n8n Webhook node URL, or a Slack incoming webhook
# (both consume {"text": "..."}). Leave unset to make notify a no-op.
NOTIFY_WEBHOOK_URL = cfg("notify_webhook_url", "NOTIFY_WEBHOOK_URL")
GEMINI_API_KEY     = cfg("gemini_api_key",     "GEMINI_API_KEY")
ANTHROPIC_API_KEY  = cfg("anthropic_api_key",  "ANTHROPIC_API_KEY")

# Environment passed to the shell tasks so the loader and dbt see the same
# project/region/profile as a local run.
PIPELINE_ENV = {
    **os.environ,
    "GCP_PROJECT":       GCP_PROJECT       or "",
    "BQ_LOCATION":       BQ_LOCATION       or "",
    "GEMINI_API_KEY":    GEMINI_API_KEY    or "",
    "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY or "",
    "PYTHONIOENCODING":  "utf-8",
}


# ── Task: resolve the statement PDF to a local path ─────────────────────────
def resolve_pdf(**context) -> str:
    """Find the PDF to process and return a local filesystem path.

    Priority: dag_run.conf['pdf_path'] -> newest object under the GCS prefix.
    A gs:// path (or a discovered GCS object) is downloaded to a temp file so
    the loader, which reads a local path, can parse it unchanged.
    """
    conf = (context.get("dag_run").conf or {}) if context.get("dag_run") else {}
    pdf_path = conf.get("pdf_path")

    if not pdf_path:
        if not GCS_BUCKET:
            raise ValueError(
                "No pdf_path in dag_run.conf and no statements_gcs_bucket set."
            )
        from airflow.providers.google.cloud.hooks.gcs import GCSHook

        hook = GCSHook()
        objects = [o for o in hook.list(GCS_BUCKET, prefix=GCS_PREFIX)
                   if o.lower().endswith(".pdf")]
        if not objects:
            raise ValueError(f"No PDFs under gs://{GCS_BUCKET}/{GCS_PREFIX}")
        pdf_path = f"gs://{GCS_BUCKET}/{sorted(objects)[-1]}"

    if pdf_path.startswith("gs://"):
        from airflow.providers.google.cloud.hooks.gcs import GCSHook

        bucket, _, obj = pdf_path[len("gs://"):].partition("/")
        local = os.path.join(tempfile.gettempdir(), os.path.basename(obj))
        GCSHook().download(bucket_name=bucket, object_name=obj, filename=local)
        return local

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(pdf_path)
    return pdf_path


# ── Task: notify a webhook (n8n / Slack) ────────────────────────────────────
def notify(**context) -> str:
    """POST a one-line success message to NOTIFY_WEBHOOK_URL.

    The payload is {"text": "..."}, which both an n8n Webhook node and a Slack
    incoming webhook accept. If no URL is configured the task is a no-op, so the
    DAG runs out of the box. Uses stdlib only (no extra Airflow deps).
    """
    if not NOTIFY_WEBHOOK_URL:
        print("notify_webhook_url not set — skipping notification.")
        return "skipped"

    import json
    import urllib.request

    pdf = context["ti"].xcom_pull(task_ids="ingest_pdf")
    message = (
        f"✅ Bank statement pipeline succeeded for {context['ds']}\n"
        f"• statement: {os.path.basename(pdf) if pdf else 'n/a'}\n"
        f"• warehouse: dbt build complete (fct_transactions refreshed)"
    )
    data = json.dumps({"text": message}).encode("utf-8")
    req = urllib.request.Request(
        NOTIFY_WEBHOOK_URL, data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(f"notify POST -> {resp.status}")
    return "sent"


with DAG(
    dag_id="bank_statement_pipeline",
    description="Ingest a bank statement PDF, load to BigQuery, run dbt.",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 1, 1, tz="Asia/Kolkata"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": pendulum.duration(minutes=5)},
    tags=["bank-statement", "bigquery", "dbt"],
    doc_md=__doc__,
) as dag:

    ingest = PythonOperator(
        task_id="ingest_pdf",
        python_callable=resolve_pdf,
    )

    # Append parsed rows into raw.bank_transactions (append-only load job).
    load = BashOperator(
        task_id="load_to_bigquery",
        bash_command=(
            f'cd "{REPO_DIR}" && '
            f'"{PYTHON_EXECUTABLE}" load_to_bigquery.py '
            '"{{ ti.xcom_pull(task_ids=\'ingest_pdf\') }}"'
        ),
        env=PIPELINE_ENV,
        append_env=False,
    )

    # Build + test the warehouse models. `dbt build` runs seeds, models and
    # data tests in dependency order; fct_transactions is incremental so this
    # only appends the newly loaded transactions.
    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=(
            f'cd "{DBT_PROJECT_DIR}" && '
            f'"{DBT_EXECUTABLE}" build'
        ),
        env=PIPELINE_ENV,
        append_env=False,
    )

    # Generate plain-English explanations for anomaly-flagged transactions and
    # write them to analytics.anomaly_explanations in BigQuery.
    # Requires GEMINI_API_KEY or ANTHROPIC_API_KEY; skipped gracefully if absent.
    explain = BashOperator(
        task_id="explain_anomalies",
        bash_command=(
            f'cd "{REPO_DIR}" && '
            f'"{PYTHON_EXECUTABLE}" ai/explain_anomalies.py --write || true'
        ),
        env=PIPELINE_ENV,
        append_env=False,
    )

    # Ping a webhook (n8n Webhook node or Slack incoming webhook) on success.
    # No-op if notify_webhook_url is unset, so the DAG runs out of the box.
    notify_task = PythonOperator(
        task_id="notify",
        python_callable=notify,
    )

    ingest >> load >> dbt_build >> explain >> notify_task
