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


# Chat web UI for the /ask text-to-SQL assistant (served at GET /).
ASK_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ask your statement</title>
<style>
 *{box-sizing:border-box}
 body{margin:0;height:100vh;display:flex;flex-direction:column;color:#0f172a;
   font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
   background:#eef1f7;background-image:radial-gradient(800px 400px at 90% -5%,rgba(79,70,229,.10),transparent 60%),
   radial-gradient(700px 380px at 0% 100%,rgba(14,165,233,.10),transparent 60%)}
 .app{width:100%;max-width:800px;margin:0 auto;flex:1;display:flex;flex-direction:column;min-height:0;padding:0 14px}
 header{padding:20px 6px 10px}
 header h1{margin:0;font-size:1.4rem;letter-spacing:-.01em}
 header p{margin:4px 0 0;color:#64748b;font-size:.9rem}
 .chat{flex:1;overflow-y:auto;padding:12px 4px;display:flex;flex-direction:column;gap:12px;min-height:0}
 .msg{max-width:84%;padding:11px 15px;border-radius:16px;white-space:pre-wrap;line-height:1.55;
   font-size:.96rem;box-shadow:0 1px 2px rgba(15,23,42,.07)}
 .msg.user{align-self:flex-end;background:linear-gradient(135deg,#4f46e5,#0ea5e9);color:#fff;border-bottom-right-radius:5px}
 .msg.bot{align-self:flex-start;background:#fff;border:1px solid #e6e9f0;border-bottom-left-radius:5px}
 .msg.err{align-self:flex-start;background:#fff1f2;border:1px solid #fecdd3;color:#9f1239}
 .dots span{display:inline-block;width:7px;height:7px;margin:0 2px;border-radius:50%;background:#94a3b8;animation:b 1s infinite}
 .dots span:nth-child(2){animation-delay:.15s} .dots span:nth-child(3){animation-delay:.3s}
 @keyframes b{0%,80%,100%{opacity:.3;transform:translateY(0)}40%{opacity:1;transform:translateY(-4px)}}
 .chips{display:flex;flex-wrap:wrap;gap:8px;padding:2px 4px}
 .chip{font-size:.82rem;color:#4f46e5;background:#eef2ff;border:1px solid #c7d2fe;border-radius:999px;
   padding:6px 12px;cursor:pointer}
 .chip:hover{background:#e0e7ff}
 .composer{display:flex;gap:8px;padding:10px 4px 16px}
 textarea{flex:1;resize:none;max-height:140px;padding:12px 15px;border:1px solid #cbd5e1;border-radius:16px;
   font:inherit;font-size:1rem;line-height:1.4;background:#fff}
 textarea:focus{outline:none;border-color:#4f46e5;box-shadow:0 0 0 3px rgba(79,70,229,.15)}
 .composer button{padding:0 22px;border:0;border-radius:16px;background:#4f46e5;color:#fff;font-weight:600;cursor:pointer}
 .composer button:disabled{opacity:.5;cursor:default}
</style></head><body>
<div class="app">
  <header>
    <h1>💬 Ask your statement</h1>
    <p>Ask in plain English — the AI writes the SQL, runs it on your BigQuery data, and answers.</p>
  </header>
  <div class="chat" id="chat">
    <div class="msg bot">Hi! Ask me anything about your transactions — spending by category, monthly trends, top merchants, anomalies…</div>
    <div class="chips" id="chips"></div>
  </div>
  <form class="composer" id="f">
    <textarea id="q" rows="1" placeholder="e.g. how much did I spend on food, by month?"></textarea>
    <button id="send">Ask</button>
  </form>
</div>
<script>
 const chat=document.getElementById('chat'),f=document.getElementById('f'),q=document.getElementById('q'),
       send=document.getElementById('send'),chips=document.getElementById('chips');
 const examples=["How much did I spend on food, by month?","What are my top 5 merchants by spend?",
   "Show my total income vs expense per month.","List my flagged anomalies."];
 examples.forEach(t=>{const c=document.createElement('button');c.type='button';c.className='chip';
   c.textContent=t;c.onclick=()=>{q.value=t;ask();};chips.appendChild(c);});
 function add(text,cls){const d=document.createElement('div');d.className='msg '+cls;d.textContent=text;
   chat.appendChild(d);chat.scrollTop=chat.scrollHeight;return d;}
 function thinking(){const d=document.createElement('div');d.className='msg bot';
   d.innerHTML='<span class="dots"><span></span><span></span><span></span></span>';
   chat.appendChild(d);chat.scrollTop=chat.scrollHeight;return d;}
 async function ask(){const text=q.value.trim();if(!text)return;
   add(text,'user');q.value='';q.style.height='auto';send.disabled=true;const t=thinking();
   try{const r=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({question:text})});const d=await r.json();t.remove();
    if(d.answer) add(d.answer.replace(/^[*-] /gm,'• '),'bot');
    else add('⚠ '+(d.error||('HTTP '+r.status)),'err');}
   catch(e){t.remove();add('⚠ '+e,'err');}
   send.disabled=false;q.focus();}
 f.onsubmit=e=>{e.preventDefault();ask();};
 q.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask();}});
 q.addEventListener('input',()=>{q.style.height='auto';q.style.height=Math.min(q.scrollHeight,140)+'px';});
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
