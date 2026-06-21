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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,600;12..96,700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
 *{box-sizing:border-box}
 :root{--f-display:'Bricolage Grotesque',system-ui,sans-serif;--f-body:'Inter',system-ui,sans-serif}
 body{margin:0;height:100vh;display:flex;flex-direction:column;color:#e8eaf2;font-size:16px;
   font-family:var(--f-body),-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;background:#07070b}
 /* full-bleed dark backdrop: bottom blue/purple glow + halftone dots (fills the side space) */
 .bg{position:fixed;inset:0;z-index:-1;
   background:radial-gradient(150% 82% at 50% 124%,rgba(124,107,255,.32),rgba(56,103,214,.14) 38%,transparent 68%),#07070b}
 .bg::after{content:"";position:absolute;inset:0;
   background-image:radial-gradient(rgba(255,255,255,.06) 1px,transparent 1.4px);background-size:24px 24px;
   -webkit-mask-image:linear-gradient(to top,#000,transparent 44%);mask-image:linear-gradient(to top,#000,transparent 44%);opacity:.7}
 .app{width:100%;max-width:760px;margin:0 auto;flex:1;display:flex;flex-direction:column;min-height:0;padding:0 16px}
 .topbar{display:flex;align-items:center;gap:10px;padding:14px 2px;color:#c3cbe0;font-size:1rem;font-family:var(--f-display);font-weight:600}
 .topbar .b{width:26px;height:26px;border-radius:8px;display:grid;place-items:center;color:#fff;font-weight:700;font-size:13px;
   background:linear-gradient(135deg,#4285f4,#a142f4)}
 .topbar .b svg{width:16px;height:16px}
 .stage{flex:1;overflow-y:auto;display:flex;flex-direction:column;min-height:0;scroll-behavior:smooth}
 /* hero (empty state) */
 .hero{margin:auto;text-align:center;padding:10px 0 30px}
 .spark{width:54px;height:54px;animation:tw 5s ease-in-out infinite,rise .6s .05s both}
 @keyframes tw{0%,100%{transform:rotate(0) scale(1)}50%{transform:rotate(10deg) scale(1.08)}}
 .hero h1{font-family:var(--f-display);font-size:clamp(30px,5.2vw,44px);font-weight:600;letter-spacing:-.02em;
   margin:18px 0 0;color:#f4f6fc;animation:rise .6s .15s both}
 .hero p{color:#9aa3b8;margin:10px 0 0;font-size:1.02rem;line-height:1.5;max-width:46ch;margin-left:auto;margin-right:auto;animation:rise .6s .22s both}
 .chips{display:flex;flex-wrap:wrap;gap:9px;justify-content:center;margin-top:24px;animation:rise .6s .3s both}
 .chip{font-size:.92rem;color:#cfd6ea;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);
   border-radius:999px;padding:9px 15px;cursor:pointer;transition:.15s}
 .chip:hover{background:rgba(255,255,255,.13);transform:translateY(-1px)}
 /* chat */
 .chat{display:flex;flex-direction:column;gap:14px;padding:8px 2px 6px}
 .row{display:flex;gap:10px;align-items:flex-start;animation:pop .34s cubic-bezier(.2,.7,.3,1)}
 .row.user{flex-direction:row-reverse}
 @keyframes pop{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
 @keyframes rise{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
 @keyframes riseUp{from{opacity:0;transform:translateY(46px)}to{opacity:1;transform:none}}
 .avatar{width:30px;height:30px;border-radius:50%;flex:none;display:grid;place-items:center;font-size:14px;margin-top:2px}
 .avatar.bot{background:linear-gradient(135deg,#4285f4,#a142f4)}
 .avatar.bot svg{width:17px;height:17px} .avatar.user{background:#2a2c38;color:#cbd2e0;font-weight:700}
 .bubble{max-width:80%;padding:12px 16px;border-radius:17px;white-space:pre-wrap;line-height:1.6;font-size:1.02rem}
 .row.user .bubble{background:linear-gradient(135deg,#4285f4,#7a5cff);color:#fff;border-bottom-right-radius:5px}
 .row.bot .bubble{background:#15161f;border:1px solid #262835;color:#e8eaf2;border-bottom-left-radius:5px}
 .row.err .bubble{background:#27151b;border:1px solid #5b2330;color:#ffb4bd}
 .caret::after{content:'▋';color:#7c86a6;margin-left:1px;animation:blink 1s steps(1) infinite}
 @keyframes blink{50%{opacity:0}}
 .dots span{display:inline-block;width:7px;height:7px;margin:0 2px;border-radius:50%;background:#7c86a6;animation:bo 1s infinite}
 .dots span:nth-child(2){animation-delay:.15s} .dots span:nth-child(3){animation-delay:.3s}
 @keyframes bo{0%,80%,100%{opacity:.3;transform:translateY(0)}40%{opacity:1;transform:translateY(-4px)}}
 /* composer pill (Gemini-style) */
 .composer{padding:10px 0 18px;animation:riseUp .6s .12s both}
 .pill{display:flex;align-items:flex-end;gap:8px;background:#14151c;border:1px solid #2a2c38;border-radius:26px;padding:7px 7px 7px 18px}
 .pill:focus-within{border-color:#4f6bff;box-shadow:0 0 0 3px rgba(79,107,255,.18)}
 .pill textarea{flex:1;background:transparent;border:0;color:#e8eaf2;font-family:var(--f-body);font-size:1.04rem;line-height:1.45;
   resize:none;max-height:150px;outline:none;padding:8px 0}
 .pill textarea::placeholder{color:#79829b}
 .pill button{flex:none;width:40px;height:40px;border-radius:50%;border:0;cursor:pointer;font-size:18px;color:#fff;
   background:linear-gradient(135deg,#4285f4,#a142f4);transition:.15s}
 .pill button:hover:not(:disabled){filter:brightness(1.08)} .pill button:active{transform:scale(.94)}
 .pill button:disabled{opacity:.45;cursor:default}
 /* topbar controls */
 .topbar .spacer{flex:1}
 .topbar select,.topbar .iconbtn{background:rgba(255,255,255,.07);color:inherit;border:1px solid rgba(255,255,255,.14);
   border-radius:10px;padding:6px 10px;font-family:var(--f-body);font-size:.82rem;cursor:pointer;transition:.15s}
 .topbar .iconbtn{font-size:1rem;line-height:1} .topbar .iconbtn:active{transform:scale(.9)}
 /* collapsible SQL under an answer */
 .sqltoggle{display:inline-block;margin-top:10px;font-size:.8rem;color:#9aa3b8;background:none;border:0;cursor:pointer;
   padding:0;font-family:var(--f-body)}
 .sqltoggle:hover{color:#cfd6ea}
 .sqlbox{margin-top:8px;overflow:hidden;max-height:0;opacity:0;transition:max-height .38s cubic-bezier(.2,.7,.3,1),opacity .3s;
   background:#0c0d14;border:1px solid #23252f;border-radius:12px}
 .sqlbox.open{max-height:560px;opacity:1}
 .sqlbox pre{margin:0;padding:12px 14px;overflow:auto;font-family:ui-monospace,Consolas,monospace;font-size:.8rem;
   line-height:1.5;color:#cdd6e6;white-space:pre-wrap}
 /* light theme (Gemini look stays dark by default; toggle to light) */
 html[data-theme="light"] body{color:#0f172a;background:#f4f6fb}
 html[data-theme="light"] .bg{background:radial-gradient(150% 82% at 50% 124%,rgba(124,107,255,.12),rgba(56,103,214,.06) 38%,transparent 68%),#f4f6fb}
 html[data-theme="light"] .bg::after{opacity:.35}
 html[data-theme="light"] .topbar{color:#334155}
 html[data-theme="light"] .topbar select,html[data-theme="light"] .topbar .iconbtn{background:#fff;border-color:#cbd5e1}
 html[data-theme="light"] .hero h1{color:#0f172a}
 html[data-theme="light"] .hero p{color:#64748b}
 html[data-theme="light"] .chip{color:#4f46e5;background:#eef2ff;border-color:#c7d2fe}
 html[data-theme="light"] .chip:hover{background:#e0e7ff}
 html[data-theme="light"] .row.bot .bubble{background:#fff;border-color:#e6e9f0;color:#0f172a}
 html[data-theme="light"] .row.err .bubble{background:#fff1f2;border-color:#fecdd3;color:#9f1239}
 html[data-theme="light"] .pill{background:#fff;border-color:#cbd5e1}
 html[data-theme="light"] .pill textarea{color:#0f172a} html[data-theme="light"] .pill textarea::placeholder{color:#94a3b8}
 html[data-theme="light"] .sqlbox{background:#f8fafc;border-color:#e2e8f0} html[data-theme="light"] .sqlbox pre{color:#334155}
 html[data-theme="light"] .sqltoggle{color:#64748b} html[data-theme="light"] .sqltoggle:hover{color:#0f172a}
 /* Material-style theme wipe */
 ::view-transition-old(root),::view-transition-new(root){animation:none;mix-blend-mode:normal}
 ::view-transition-new(root){z-index:2147483646} ::view-transition-old(root){z-index:1}
 @media(prefers-reduced-motion:reduce){*{animation:none!important}}
</style></head><body>
<div class="bg"></div>
<div class="app">
  <div class="topbar"><span class="b">✦</span> Ask your statement
    <span class="spacer"></span>
    <select id="model" title="Gemini model">
      <option value="gemini-2.5-flash">2.5 Flash</option>
      <option value="gemini-2.5-flash-lite">2.5 Flash-Lite</option>
      <option value="gemini-2.0-flash-lite">2.0 Flash-Lite</option>
    </select>
    <button id="theme" class="iconbtn" type="button" title="Toggle light / dark">☀️</button>
  </div>
  <div class="stage" id="stage">
    <div class="hero" id="hero">
      <svg class="spark" viewBox="0 0 24 24" aria-hidden="true"><defs>
        <linearGradient id="sg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#4285f4"/><stop offset=".4" stop-color="#a142f4"/>
          <stop offset=".72" stop-color="#ea4335"/><stop offset="1" stop-color="#fbbc05"/></linearGradient></defs>
        <path fill="url(#sg)" d="M12 0C13 7 17 11 24 12C17 13 13 17 12 24C11 17 7 13 0 12C7 11 11 7 12 0Z"/></svg>
      <h1>What would you like to know?</h1>
      <p>Ask in plain English — the AI writes the SQL, runs it on your BigQuery data, and answers.</p>
      <div class="chips" id="chips"></div>
    </div>
    <div class="chat" id="chat"></div>
  </div>
  <form class="composer" id="f">
    <div class="pill">
      <textarea id="q" rows="1" placeholder="Ask your statement…"></textarea>
      <button id="send" type="submit" aria-label="Ask">↑</button>
    </div>
  </form>
</div>
<script>
 const stage=document.getElementById('stage'),chat=document.getElementById('chat'),hero=document.getElementById('hero'),
       f=document.getElementById('f'),q=document.getElementById('q'),send=document.getElementById('send'),
       chips=document.getElementById('chips');
 const SPARK='<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#fff" d="M12 0C13 7 17 11 24 12C17 13 13 17 12 24C11 17 7 13 0 12C7 11 11 7 12 0Z"/></svg>';
 const examples=["How much did I spend on food, by month?","What are my top 5 merchants by spend?",
   "Show my total income vs expense per month.","List my flagged anomalies."];
 examples.forEach(t=>{const c=document.createElement('button');c.type='button';c.className='chip';
   c.textContent=t;c.onclick=()=>{q.value=t;ask();};chips.appendChild(c);});

 // model picker (persisted)
 const modelSel=document.getElementById('model');
 modelSel.value=localStorage.getItem('model')||'gemini-2.5-flash';
 modelSel.onchange=()=>localStorage.setItem('model',modelSel.value);

 // light/dark toggle with a Material-style circular wipe
 const root=document.documentElement, themeBtn=document.getElementById('theme');
 root.dataset.theme=localStorage.getItem('theme')||'dark';
 const syncTheme=()=>themeBtn.textContent=root.dataset.theme==='light'?'🌙':'☀️';
 syncTheme();
 themeBtn.onclick=()=>{
   const tn=root.dataset.theme==='light'?'dark':'light';
   const go=()=>{root.dataset.theme=tn;localStorage.setItem('theme',tn);syncTheme();};
   if(!document.startViewTransition){go();return;}
   const r=themeBtn.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2,
         end=Math.hypot(Math.max(x,innerWidth-x),Math.max(y,innerHeight-y));
   document.startViewTransition(go).ready.then(()=>document.documentElement.animate(
     {clipPath:[`circle(0px at ${x}px ${y}px)`,`circle(${end}px at ${x}px ${y}px)`]},
     {duration:520,easing:'cubic-bezier(.22,.61,.36,1)',pseudoElement:'::view-transition-new(root)'}));
 };

 // collapsible SQL under an answer
 function attachSQL(bubble,sqls){
   const btn=document.createElement('button'); btn.className='sqltoggle'; btn.textContent='⚙ Show SQL ('+sqls.length+')';
   const box=document.createElement('div'); box.className='sqlbox';
   const pre=document.createElement('pre'); pre.textContent=sqls.join(';\\n\\n'); box.appendChild(pre);
   btn.onclick=()=>{const open=box.classList.toggle('open');
     btn.textContent=(open?'⚙ Hide SQL (':'⚙ Show SQL (')+sqls.length+')'; stage.scrollTop=stage.scrollHeight;};
   bubble.appendChild(btn); bubble.appendChild(box);
 }

 function hideHero(){ if(hero && !hero.dataset.gone){hero.dataset.gone='1';
   hero.style.transition='opacity .35s,transform .35s';hero.style.opacity='0';hero.style.transform='translateY(-12px)';
   setTimeout(()=>{hero.style.display='none';},360);} }
 function add(cls){
   const r=document.createElement('div'); r.className='row '+(cls==='user'?'user':cls==='err'?'err':'bot');
   const av=document.createElement('div'); av.className='avatar '+(cls==='user'?'user':'bot');
   if(cls==='user') av.textContent='🧑'; else av.innerHTML=SPARK;
   const b=document.createElement('div'); b.className='bubble';
   r.appendChild(av); r.appendChild(b); chat.appendChild(r); stage.scrollTop=stage.scrollHeight;
   return {row:r, bubble:b};
 }
 function thinking(){ const {row,bubble}=add('bot');
   bubble.innerHTML='<span class="dots"><span></span><span></span><span></span></span>'; return row; }
 function typewrite(el,text){               // ChatGPT/Claude-style streamed reveal
   el.textContent=''; el.classList.add('caret');
   let i=0; const step=Math.max(2,Math.ceil(text.length/45));
   (function tick(){ i+=step; el.textContent=text.slice(0,i); stage.scrollTop=stage.scrollHeight;
     if(i<text.length) requestAnimationFrame(tick); else el.classList.remove('caret'); })();
 }
 function friendly(err){
   const s=String(err);
   if(/RESOURCE_EXHAUSTED|429|quota/i.test(s))
     return "⏳ Free-tier limit reached for now. Gemini's free tier allows only a small number of requests per day "
          + "— wait a bit and retry, set GEMINI_MODEL to a lighter model like gemini-2.5-flash-lite, or use a Claude key.";
   if(/503|UNAVAILABLE|high demand|overloaded/i.test(s))
     return "🛰️ The model is briefly busy (high demand) — this is temporary. Try again in a few seconds, or switch "
          + "GEMINI_MODEL to gemini-2.5-flash-lite.";
   if(/No LLM key|API_KEY/i.test(s))
     return "🔑 No AI key set. Set GEMINI_API_KEY (free) or ANTHROPIC_API_KEY, then restart the server.";
   return "⚠ "+(s.length>240?s.slice(0,240)+'…':s);
 }
 async function ask(){
   const text=q.value.trim(); if(!text) return;
   hideHero();
   add('user').bubble.textContent=text;
   q.value=''; q.style.height='auto'; send.disabled=true;
   const t=thinking();
   try{
     const r=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},
       body:JSON.stringify({question:text, model:modelSel.value})});
     const d=await r.json(); t.remove();
     if(d.answer){ const b=add('bot').bubble; typewrite(b, d.answer.replace(/^[*-] /gm,'• '));
       if(d.sql && d.sql.length) attachSQL(b, d.sql); }
     else add('err').bubble.textContent=friendly(d.error||('HTTP '+r.status));
   }catch(e){ t.remove(); add('err').bubble.textContent=friendly(e); }
   send.disabled=false; q.focus();
 }
 f.onsubmit=e=>{e.preventDefault();ask();};
 q.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask();}});
 q.addEventListener('input',()=>{q.style.height='auto';q.style.height=Math.min(q.scrollHeight,150)+'px';});
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
    model = (data.get("model") or "").strip() or None
    try:
        from ai.ask_statement import ask
    except Exception:
        return jsonify(error="AI feature unavailable: install the SDK and set "
                             "GEMINI_API_KEY (free) or ANTHROPIC_API_KEY"), 503
    try:
        result = ask(question, model=model, return_sql=True)
        return jsonify(question=question, answer=result["answer"], sql=result["sql"]), 200
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
