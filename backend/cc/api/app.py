"""FastAPI application: REST + WebSocket + built dashboard on one local port."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import ValidationError

from .. import __version__
from ..agents.llm import AIUnavailable
from ..config import PROJECT_ROOT, EnvConfig, load_environment
from ..data.models import DataUnavailable
from ..services.paper import ExecutionRefused
from .container import Services, build_services
from .routes import router
from .security import respond, sanitize, token_ok

log = logging.getLogger("cc")
DIST = PROJECT_ROOT / "web" / "dist"


def _quiet_connection_resets(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    """Windows' proactor loop logs a traceback whenever a browser drops a connection; that is not an error."""
    if isinstance(context.get("exception"), ConnectionResetError):
        return
    loop.default_exception_handler(context)


def _decode_token(protocol: str | None) -> str | None:
    if not protocol:
        return None
    raw = protocol.removeprefix("cc-token.")
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def create_app(env: EnvConfig | None = None, services: Services | None = None, start_background: bool = True) -> FastAPI:
    if services is None:
        load_environment()
        env = env or EnvConfig.from_env()
        services = build_services(env)
    env = services.env

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(_quiet_connection_resets)
        services.bus.bind_loop(loop)
        task = None
        if start_background:
            task = asyncio.create_task(services.monitor.run())
            services.timeline.add("system", f"DalalSight v{__version__} started on http://{env.host}:{env.port}")
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="DalalSight", version=__version__, lifespan=lifespan, docs_url="/api/docs",
                  openapi_url="/api/openapi.json")
    app.state.services = services

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        # The docs and OpenAPI schema are guarded too: a public server must not publish its API map.
        if env.access_token and path.startswith("/api"):
            provided = request.headers.get("x-access-token") or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            if not token_ok(env.access_token, provided):
                return respond({"detail": "access token required"}, 401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # Added after the guard so CORS is the outermost layer: preflights are answered before the token check and
    # 401 responses still carry CORS headers, so a dashboard hosted elsewhere (e.g. Vercel) can prompt for the token.
    origins = [*(("http://localhost:5173", "http://127.0.0.1:5173") if env.dev_mode else ()), *env.cors_origins]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(DataUnavailable)
    async def _unavailable(_: Request, exc: DataUnavailable):
        return respond({"detail": exc.to_dict()}, 503)

    @app.exception_handler(AIUnavailable)
    async def _ai(_: Request, exc: AIUnavailable):
        return respond({"detail": {"status": "unavailable", "what": "AI model", "reason": str(exc)}}, 503)

    @app.exception_handler(ExecutionRefused)
    async def _refused(_: Request, exc: ExecutionRefused):
        return respond({"detail": str(exc)}, 403)

    @app.exception_handler(ValueError)
    async def _value(_: Request, exc: ValueError):
        return respond({"detail": str(exc)}, 422)

    @app.exception_handler(ValidationError)
    async def _validation(_: Request, exc: ValidationError):
        return respond({"detail": [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]}, 422)

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_: Request, exc: RequestValidationError):
        return respond({"detail": [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]}, 422)

    app.include_router(router)

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        # Browsers cannot set headers on WebSocket requests, so the token travels as a base64url
        # subprotocol ("cc-token.<b64>") instead of the URL, keeping it out of logs and history.
        offered = [p.strip() for p in ws.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
        token_protocol = next((p for p in offered if p.startswith("cc-token.")), None)
        if env.access_token and not token_ok(env.access_token, _decode_token(token_protocol)):
            await ws.close(code=4401)
            return
        await ws.accept(subprotocol=token_protocol)
        queue = services.bus.subscribe()
        await ws.send_text(json.dumps(sanitize({"type": "hello", "data": {"version": __version__, "monitor": services.monitor.status()}})))

        async def sender():
            while True:
                message = await queue.get()
                await ws.send_text(json.dumps(sanitize(message), default=str))

        async def receiver():
            while True:
                text = await ws.receive_text()
                if text == "ping" or '"ping"' in text:
                    await ws.send_text('{"type":"pong"}')

        tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except WebSocketDisconnect:
            pass
        finally:
            for task in tasks:
                task.cancel()
            services.bus.unsubscribe(queue)

    if DIST.exists():
        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith(("api/", "ws")):
                return respond({"detail": "not found"}, 404)
            candidate = (DIST / path).resolve()
            if path and candidate.is_file() and DIST.resolve() in candidate.parents:
                # bundles in assets/ have content-hashed names; everything else must revalidate
                hashed = candidate.parent.name == "assets"
                return FileResponse(candidate, headers={"Cache-Control": "public, max-age=31536000, immutable" if hashed else "no-cache"})
            # index.html names the current bundle: never serve a stale copy after a rebuild
            return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})

    return app
