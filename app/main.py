from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.auth import authenticate_user, require_authenticated_user
from app.config import Settings, get_settings
from app.ollama import OllamaClient
from app.schemas import ChatRequest, ConversationResponse, LoginRequest, MessageResponse
from app.storage import Storage, build_conversation_title


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
STATIC_VERSION = str(
    max(
        (BASE_DIR / "static" / "app.js").stat().st_mtime_ns,
        (BASE_DIR / "static" / "styles.css").stat().st_mtime_ns,
    )
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.storage.initialize()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    storage = Storage(settings.database_path)
    ollama_client = OllamaClient(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
    )

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.settings = settings
    app.state.storage = storage
    app.state.ollama = ollama_client

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=settings.session_cookie_name,
        same_site="lax",
        https_only=settings.session_cookie_secure,
        max_age=60 * 60 * 24 * 7,
    )
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "app_name": settings.app_name,
                "authenticated": bool(request.session.get("authenticated")),
                "static_version": STATIC_VERSION,
            },
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/health")
    async def api_health(request: Request) -> dict[str, object]:
        try:
            await request.app.state.ollama.health_check()
            ollama_status = "ok"
        except (httpx.HTTPError, ValueError) as exc:
            ollama_status = f"unavailable: {exc.__class__.__name__}"

        return {
            "status": "ok",
            "ollama": ollama_status,
            "model": settings.ollama_model,
        }

    @app.get("/api/auth/me")
    async def auth_me(request: Request) -> dict[str, bool]:
        return {"authenticated": bool(request.session.get("authenticated"))}

    @app.post("/api/auth/login")
    async def login(payload: LoginRequest, request: Request) -> JSONResponse:
        if not authenticate_user(settings, payload.username, payload.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials.",
            )

        request.session.clear()
        request.session["authenticated"] = True
        request.session["username"] = settings.admin_username
        return JSONResponse({"authenticated": True})

    @app.post("/api/auth/logout")
    async def logout(request: Request) -> JSONResponse:
        request.session.clear()
        return JSONResponse({"authenticated": False})

    @app.get(
        "/api/conversations",
        dependencies=[Depends(require_authenticated_user)],
        response_model=list[ConversationResponse],
    )
    async def list_conversations(request: Request) -> list[dict[str, object]]:
        return request.app.state.storage.list_conversations()

    @app.get(
        "/api/conversations/{conversation_id}/messages",
        dependencies=[Depends(require_authenticated_user)],
        response_model=list[MessageResponse],
    )
    async def get_conversation_messages(
        conversation_id: int, request: Request
    ) -> list[dict[str, object]]:
        storage: Storage = request.app.state.storage
        if not storage.conversation_exists(conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found.")
        return storage.get_messages(conversation_id)

    @app.post(
        "/api/chat/stream",
        dependencies=[Depends(require_authenticated_user)],
    )
    async def stream_chat(payload: ChatRequest, request: Request) -> StreamingResponse:
        storage: Storage = request.app.state.storage
        conversation_id = payload.conversation_id
        if conversation_id is None:
            conversation_id = storage.create_conversation(
                build_conversation_title(payload.prompt)
            )
        elif not storage.conversation_exists(conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found.")

        storage.add_message(conversation_id, "user", payload.prompt)
        history = storage.get_messages(conversation_id)
        model_messages = [
            {"role": message["role"], "content": message["content"]}
            for message in history
        ]

        async def event_stream() -> AsyncIterator[str]:
            yield _sse_message(
                "conversation",
                {
                    "conversation_id": conversation_id,
                    "title": build_conversation_title(payload.prompt),
                },
            )

            full_response: list[str] = []
            try:
                async for chunk in request.app.state.ollama.stream_chat(model_messages):
                    full_response.append(chunk)
                    yield _sse_message("chunk", {"content": chunk})
            except (httpx.HTTPError, ValueError) as exc:
                yield _sse_message(
                    "error",
                    {"detail": f"Ollama request failed: {exc.__class__.__name__}"},
                )
                return

            assistant_message = "".join(full_response).strip()
            if assistant_message:
                storage.add_message(conversation_id, "assistant", assistant_message)

            yield _sse_message("done", {"conversation_id": conversation_id})

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app


def _sse_message(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


app = create_app()
