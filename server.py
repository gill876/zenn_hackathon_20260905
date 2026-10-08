"""
AsobiAgent server (FastAPI).

- POST /webhook          LINE Messaging API webhook (signature-checked)
- /api/*                 web simulator (public replay; free-text chat needs the admin token)
- /agent/*, /demo-venue  form agent demo pages
- /                      simulator page and pitch decks
"""

import json
import logging
import os
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from bot.deps import Deps, build_deps
from bot.handler import handle_payload
from config import get_settings
from services.line_api import HttpLineApi, RecordingLineApi, verify_signature
from services.store import MemoryStore
from web import agent_pages, simulator

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("server")

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def default_deps() -> Deps:
    settings = get_settings()
    if settings.store_backend == "firestore":
        from services.firestore_store import FirestoreStore
        store = FirestoreStore(project=settings.gcp_project or None)
    else:
        store = MemoryStore()
    line = HttpLineApi(settings.line_channel_access_token) if settings.line_channel_access_token else RecordingLineApi()
    deps = build_deps(settings, store, line)
    if settings.form_agent_mode == "job" and settings.gcp_project:
        from agents.form_agent import CloudRunJobRunner
        deps.form_agent = CloudRunJobRunner(settings.gcp_project, settings.region, settings.form_agent_job)
    elif settings.form_agent_mode == "local":
        from agents.form_agent import LocalRunner
        deps.form_agent = LocalRunner(store, deps.llm, deps.base_url())
    return deps


def create_app(deps: Optional[Deps] = None) -> FastAPI:
    app = FastAPI(title="AsobiAgent", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.deps = deps or default_deps()
    app.include_router(simulator.router)
    app.include_router(agent_pages.router)

    @app.post("/webhook")
    async def line_webhook(request: Request) -> JSONResponse:
        d: Deps = request.app.state.deps
        if not d.settings.line_channel_secret:
            return JSONResponse({"error": "LINE is not configured"}, status_code=503)
        body = await request.body()
        if not verify_signature(d.settings.line_channel_secret, body, request.headers.get("x-line-signature")):
            return JSONResponse({"error": "invalid signature"}, status_code=400)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return JSONResponse({"error": "invalid body"}, status_code=400)
        # Handled before responding: Cloud Run only guarantees CPU while a request is open.
        await handle_payload(d, payload)
        return JSONResponse({"ok": True})

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def _page(name: str) -> HTMLResponse:
        path = os.path.join(STATIC_DIR, name)
        if not os.path.exists(path):
            return HTMLResponse("Not Found", status_code=404)
        with open(path, encoding="utf-8") as f:
            return HTMLResponse(f.read())

    @app.get("/", response_class=HTMLResponse)
    async def root() -> HTMLResponse:
        return _page("index.html")

    @app.get("/privacy", response_class=HTMLResponse)
    async def privacy() -> HTMLResponse:
        return _page("privacy.html")

    @app.get("/presentation", response_class=HTMLResponse)
    @app.get("/presentation_ja.html", response_class=HTMLResponse)
    async def presentation_ja() -> HTMLResponse:
        return _page("presentation_ja.html")

    @app.get("/presentation_en", response_class=HTMLResponse)
    @app.get("/presentation_en.html", response_class=HTMLResponse)
    async def presentation_en() -> HTMLResponse:
        return _page("presentation_en.html")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
