# Command Reference

All the terminal commands for this project, step by step. Examples use **Windows
PowerShell** (the primary dev environment).

> **Replace the placeholders** with your own values:
> `<your-gcp-project>`, `<your-region>` (e.g. `asia-south1`), `<your-gemini-key>`,
> and `"your-statement.pdf"` (path to your PDF). Run everything from the repo
> root unless a step says otherwise.

> **Two Python environments** (this trips people up):
> - **`python`** (Python 3.10+/3.14) → analyser, Flask server, loader, AI scripts
> - **`~/dbt-venv`** (Python 3.12) → **dbt only** — activate it first
>
> **macOS/Linux:** swap `$env:VAR="x"` → `export VAR=x`, and
> `…\Scripts\Activate.ps1` → `source ~/dbt-venv/bin/activate`.

---

## 0 · One-time setup
```powershell
git clone https://github.com/ARAVINDHRAJA123/Bank-Statement-Analyser.git
cd Bank-Statement-Analyser

# Python deps for the analyser, server, loader, AI (Python 3.10+)
python -m pip install -r requirements.txt

# authenticate to Google Cloud (once) — needed for BigQuery
gcloud auth application-default login

# create the dbt virtualenv (Python 3.12) and install dbt
py -3.12 -m venv $HOME\dbt-venv
$HOME\dbt-venv\Scripts\Activate.ps1
python -m pip install dbt-bigquery
deactivate
```

## 1 · Environment variables — set in each new terminal (BigQuery / dbt / AI)
```powershell
$env:GCP_PROJECT      = "<your-gcp-project>"
$env:BQ_LOCATION      = "<your-region>"          # e.g. asia-south1; must match your raw dataset
$env:PYTHONIOENCODING = "utf-8"                  # avoids unicode errors on Windows
$env:GEMINI_API_KEY   = "<your-gemini-key>"      # only for the AI features (free: aistudio.google.com)
```

## 2 · Generate the Excel report (the analyser)
```powershell
python Bank_Statement_Analyser.py "your-statement.pdf"
# → produces Bank_Statement_Report.xlsx
```

## 3 · Run the tests
```powershell
python -m pytest -q
```

## 4 · n8n automation (auto-report from Google Drive)
```powershell
# terminal 1 — the Flask bridge
python server.py

# terminal 2 — n8n
npm install -g n8n
n8n start
# open http://localhost:5678  →  import workflow_automation.json
```

## 5 · Load a statement into BigQuery
```powershell
python load_to_bigquery.py "your-statement.pdf"
```

## 6 · dbt — build & test the warehouse (inside the venv)
```powershell
$HOME\dbt-venv\Scripts\Activate.ps1
cd dbt_bank

dbt debug                 # check the connection
dbt build                 # seeds + models + tests (fct_transactions is incremental)
dbt build --full-refresh  # rebuild everything from scratch (e.g. re-score anomalies)
dbt test                  # run just the data tests
dbt docs generate         # build the docs
dbt docs serve            # interactive lineage graph
deactivate                # leave the venv when done
```

## 7 · AI assistant (free Gemini or Claude)
```powershell
# pick ONE key (auto-detected):  $env:GEMINI_API_KEY (free)  or  $env:ANTHROPIC_API_KEY

# A) Web chat UI
python server.py                                  # then open http://localhost:5050/

# B) Command line — ask against BigQuery warehouse
python ai\ask_statement.py "how much did I spend on food, by month?"

# C) Offline mode — answer from PDF directly, no BigQuery needed
python ai\ask_statement.py "what is my top category?" --pdf "statement.pdf"

# D) Explain the flagged anomalies
python ai\explain_anomalies.py                    # print plain-English reasons
python ai\explain_anomalies.py --write            # also save to BigQuery

# Optional: choose a model with more free quota
$env:GEMINI_MODEL="gemini-2.5-flash-lite"
```

## 8 · Airflow (Astro CLI — local DAG UI)
```bash
# start (Docker must be running)
cd airflow/astro
astro dev start
# → open http://astro.localhost:6563  (admin / admin)

# stop
astro dev stop

# trigger the DAG manually (pass a PDF path)
astro dev run dags trigger bank_statement_pipeline --conf '{"pdf_path":"/abs/path/to/statement.pdf"}'

# view task logs
astro dev logs

# restart after editing the DAG
astro dev restart
```

## 9 · Git
```powershell
git status
git pull                       # get latest before working
git add .
git commit -m "your message"
git push
```

## 10 · Recreate the dbt venv (if it ever breaks)
```powershell
winget install -e --id Python.Python.3.12         # if Python 3.12 is missing
Remove-Item -Recurse -Force $HOME\dbt-venv
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv $HOME\dbt-venv
$HOME\dbt-venv\Scripts\Activate.ps1
python -m pip install dbt-bigquery
dbt --version
```

## Handy
```powershell
$env:FLASK_DEBUG="1"; python server.py            # auto-reload the server while editing
python --version                                  # confirm the app/AI env (3.10+)
$HOME\dbt-venv\Scripts\python.exe --version        # confirm the dbt venv (3.12)
```

---

## Which terminal runs what
| Task | Interpreter | Run from |
|------|-------------|----------|
| Excel report, tests, loader, AI scripts, server | `python` (3.10+) | repo root |
| Anything `dbt …` | activated `~/dbt-venv` (3.12) | `dbt_bank/` |
| `n8n` | Node.js | anywhere |
| `astro dev …` (local Airflow UI) | Docker + Astro CLI | `airflow/astro/` |

> Tip: keep dbt and the AI library (`google-genai` / `anthropic`) in **separate
> environments** — installing the AI SDK into the dbt venv causes a dependency clash.
