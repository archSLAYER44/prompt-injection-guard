"""The CHAT product site: an ordinary assistant called Nimbus, served on its own port, with the guard in front.

    .venv/bin/uvicorn chat_api:app --port 8001     # then open http://localhost:8001/

This is what an end user (or the presenter) talks to. It has no dashboard pages and no links to them: it serves
web/assistant.html at / with its own light theme (web/_head_chat.html) and the guard's core API from api.py
(status, presets, chat, conversations, connection). Every request goes through the same guard_core.handle_request()
and is appended to the same log file (guard_log.py), which is how the dashboard on port 8000 sees the chats live.
The product name is BRAND below; the page reads it from /api/brand. API keys travel in request bodies and are used
for that call only.
"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

import api

BRAND = "Nimbus"
TAGLINE = "your AI assistant"

app = FastAPI(title=f"{BRAND} chat", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(api.WEB / "static")), name="static")
app.include_router(api.core)


@app.on_event("startup")
def warm():
    api.warm()


@app.get("/api/brand")
def brand():
    return {"name": BRAND, "tagline": TAGLINE}


@app.get("/favicon.ico")
def favicon():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" rx="6" fill="#4f46e5"/>'
           '<path fill="#fff" d="M7 8.5A2.5 2.5 0 0 1 9.5 6h5A2.5 2.5 0 0 1 17 8.5v4a2.5 2.5 0 0 1-2.5 2.5H11l-3 2.5V15A2.5 2.5 0 0 1 7 12.5z"/></svg>')
    return Response(svg, media_type="image/svg+xml")


@app.get("/")
def home():
    html = (api.WEB / "assistant.html").read_text(encoding="utf-8")
    html = html.replace("<!--HEAD-->", (api.WEB / "_head_chat.html").read_text(encoding="utf-8"))
    return HTMLResponse(html.replace("{{BRAND}}", BRAND))
