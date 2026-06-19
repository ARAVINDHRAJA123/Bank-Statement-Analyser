"""
Flask server for the bank-statement analyser n8n pipeline.

Rewritten from the original to fix four problems:
  1. Hardcoded Windows paths (C:\\GIT_Projects\\...) — broke on any other
     machine and on the Linux/Docker deployment target. Now uses pathlib +
     an env var, with a sensible local default.
  2. subprocess shelling out to a hardcoded script (with a filename-case
     mismatch that fails on Linux). Now imports analyse() and calls it.
  3. No error handling — a failed run returned a raw 500 stack trace. Now
     returns structured JSON errors with appropriate status codes.
  4. A single shared global output file + global last_stats — two concurrent
     requests clobbered each other. Each request now writes a uniquely-named
     report and /download fetches it by name (with a path-traversal guard).

Run:
    pip install -r requirements.txt
    python server.py
Configure (optional):
    BANK_OUTPUT_DIR   directory for generated reports (default: ./reports)
    BANK_MAX_PDF_MB   max upload size in MB (default: 20)
"""
from __future__ import annotations

import logging
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_file

from Bank_Statement_Analyser import analyse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bank-server")

OUTPUT_DIR = Path(os.environ.get("BANK_OUTPUT_DIR", "reports")).resolve()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
MAX_PDF_MB = int(os.environ.get("BANK_MAX_PDF_MB", "20"))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_PDF_MB * 1024 * 1024


def _looks_like_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"


# Minimal web UI for the /ask text-to-SQL assistant (served at GET /).
ASK_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ask your statement</title>
<style>
 body{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:680px;
   margin:40px auto;padding:0 16px;color:#0f172a;line-height:1.6}
 h1{font-size:1.5rem;margin:0 0 4px} p{color:#64748b;margin:0 0 20px}
 form{display:flex;gap:8px} input{flex:1;padding:11px 14px;border:1px solid #cbd5e1;
   border-radius:10px;font-size:1rem} button{padding:11px 18px;border:0;border-radius:10px;
   background:#4f46e5;color:#fff;font-weight:600;cursor:pointer}
 #out{margin-top:20px;padding:16px;background:#f8fafc;border:1px solid #e2e8f0;
   border-radius:10px;white-space:pre-wrap;min-height:28px}
</style></head><body>
<h1>💬 Ask your statement</h1>
<p>Ask a question about your transactions — the AI writes the query and answers.</p>
<form id="f">
  <input id="q" autocomplete="off"
    placeholder="e.g. how much did I spend on food, by month?">
  <button>Ask</button>
</form>
<div id="out"></div>
<script>
 const f=document.getElementById('f'),q=document.getElementById('q'),out=document.getElementById('out');
 f.onsubmit=async e=>{e.preventDefault();if(!q.value.trim())return;out.textContent='Thinking…';
  try{const r=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({question:q.value})});const d=await r.json();
   out.textContent=d.answer||('Error: '+(d.error||('HTTP '+r.status)));}
  catch(err){out.textContent='Error: '+err;}};
</script></body></html>"""


@app.post("/analyse")
def analyse_endpoint():
    pdf_data = request.get_data()
    if not pdf_data:
        return jsonify(error="empty request body; POST the PDF bytes"), 400
    if not _looks_like_pdf(pdf_data):
        return jsonify(error="body does not look like a PDF (missing %PDF- header)"), 400

    today = datetime.now()
    token = f"{today:%d-%m-%Y}_{uuid.uuid4().hex[:8]}"
    report_name = f"Bank_Statement_Report_{token}.xlsx"
    report_path = OUTPUT_DIR / report_name

    # Write the upload to a temp file, run, then always clean the temp file up.
    tmp_pdf = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(pdf_data)
            tmp_pdf = fh.name

        stats = analyse(tmp_pdf, str(report_path))

        stats["report_file"] = report_name
        stats["drive_folder"] = f"Output_{today:%d-%m-%Y}"
        stats["drive_file"] = report_name
        log.info("analysed %s -> %s (%d txns)", tmp_pdf, report_name, stats["transactions"])
        return jsonify(stats), 200

    except ValueError as e:
        # Expected, user-facing failure (e.g. scanned PDF, no transactions).
        log.warning("analyse rejected input: %s", e)
        return jsonify(error=str(e)), 422
    except Exception:  # noqa: BLE001 — last-resort guard so n8n gets JSON, not HTML
        log.exception("unexpected failure during analysis")
        return jsonify(error="internal error while processing the statement"), 500
    finally:
        if tmp_pdf and os.path.exists(tmp_pdf):
            os.unlink(tmp_pdf)


@app.get("/download")
def download_endpoint():
    name = request.args.get("file", "")
    if not name:
        return jsonify(error="missing 'file' query parameter"), 400

    # Path-traversal guard: only allow a bare filename that resolves inside
    # OUTPUT_DIR. Rejects names with separators, '..', absolute paths, etc.
    candidate = (OUTPUT_DIR / name).resolve()
    if candidate.parent != OUTPUT_DIR or not candidate.is_file():
        return jsonify(error="file not found"), 404

    return send_file(
        candidate,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="Bank_Statement_Report.xlsx",
    )


@app.post("/ask")
def ask_endpoint():
    """Agentic text-to-SQL over the BigQuery marts (see ai/ask_statement.py).
    Lazily imported so the core pipeline still runs without the AI deps/key."""
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify(error="missing 'question' in JSON body"), 400
    try:
        from ai.ask_statement import ask
    except Exception:
        return jsonify(error="AI feature unavailable: pip install anthropic and "
                             "set ANTHROPIC_API_KEY"), 503
    try:
        return jsonify(question=question, answer=ask(question)), 200
    except Exception as e:
        log.exception("ask endpoint failed")
        return jsonify(error=f"{type(e).__name__}: {e}"), 500


@app.get("/")
def home():
    """Minimal web UI for asking the text-to-SQL assistant a question."""
    return ASK_PAGE


@app.get("/health")
def health():
    return jsonify(status="ok"), 200


if __name__ == "__main__":
    # debug=False by default; set FLASK_DEBUG=1 locally if you want reloads.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5050")),
            debug=os.environ.get("FLASK_DEBUG") == "1")
