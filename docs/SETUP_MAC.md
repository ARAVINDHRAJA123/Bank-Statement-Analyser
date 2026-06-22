# macOS Setup (Apple Silicon)

Get the project running on a fresh Mac (M-series). Commands are **zsh / bash**.

> **Replace placeholders:** `<your-gcp-project>`, `<your-region>` (e.g. `asia-south1`),
> `<your-gemini-key>`. For Windows/PowerShell instead, see [`COMMANDS.md`](COMMANDS.md).

> **Two virtualenvs on purpose:** `~/bsa-venv` (analyser + Flask server + loader +
> AI) and `~/dbt-venv` (**dbt only**). Keeping them separate avoids a protobuf
> dependency clash between dbt and the AI SDKs. One Python (3.12) works for both.

---

## 1 · Install Homebrew + tools
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
# run the "Next steps" Homebrew prints (adds brew to PATH via ~/.zprofile), then:
brew install git python@3.12 node
brew install --cask google-cloud-sdk
```
Reopen Terminal, then verify: `python3.12 --version` and `gcloud --version`.

## 2 · Clone the repo
```bash
git clone https://github.com/ARAVINDHRAJA123/Bank-Statement-Analyser.git
cd Bank-Statement-Analyser
```

## 3 · Create the two virtualenvs
```bash
# app + AI
python3.12 -m venv ~/bsa-venv
source ~/bsa-venv/bin/activate
pip install --upgrade pip && pip install -r requirements.txt
deactivate

# dbt only
python3.12 -m venv ~/dbt-venv
source ~/dbt-venv/bin/activate
pip install dbt-bigquery
deactivate
```

## 4 · Create the dbt profile (`~/.dbt/profiles.yml` is not in git)
```bash
mkdir -p ~/.dbt
cat > ~/.dbt/profiles.yml <<'YAML'
bank_statements:
  target: dev
  outputs:
    dev:
      type: bigquery
      method: oauth
      project: "{{ env_var('GCP_PROJECT') }}"
      dataset: analytics
      location: "{{ env_var('BQ_LOCATION', 'US') }}"
      threads: 4
      timeout_seconds: 300
      priority: interactive
      maximum_bytes_billed: 1000000000
YAML
```

## 5 · Authenticate to Google Cloud
```bash
gcloud auth application-default login
```

## 6 · Environment variables (per session, or add to `~/.zshrc`)
```bash
export GCP_PROJECT="<your-gcp-project>"
export BQ_LOCATION="<your-region>"          # must match your raw dataset's region
export GEMINI_API_KEY="<your-gemini-key>"   # AI only — free key at aistudio.google.com
```

## 7 · Run it
```bash
# Analyser / tests / server / AI  → app venv
source ~/bsa-venv/bin/activate
python Bank_Statement_Analyser.py "your-statement.pdf"   # Excel report
python -m pytest -q                                      # tests
python server.py                                         # web UI → http://localhost:5050
python ai/ask_statement.py "how much did I spend on food, by month?"
deactivate

# Load to BigQuery (app venv) + build the warehouse (dbt venv)
source ~/bsa-venv/bin/activate && python load_to_bigquery.py "your-statement.pdf" && deactivate
source ~/dbt-venv/bin/activate && cd dbt_bank && dbt debug && dbt build
```

---

## Notes
- **Apple Silicon:** all dependencies ship arm64 wheels — installs are fast, nothing special needed.
- **Which venv runs what:** `~/bsa-venv` for the analyser/server/loader/AI; `~/dbt-venv` for `dbt …` (from `dbt_bank/`). Never install the AI SDKs into the dbt venv.
- **Files not in git** (gitignored — recreate or copy manually): `~/.dbt/profiles.yml` (step 4), and any personal notes (`CLAUDE.md`, `docs/PROJECT_GUIDE.md`).
- Full per-task command list: [`COMMANDS.md`](COMMANDS.md).
