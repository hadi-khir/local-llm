from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.auth import authenticate_user, require_authenticated_user
from app.config import Settings, get_settings
from app.files import guess_content_type, is_allowed, save_upload
from app.generation import GenerationManager
from app.ollama import OllamaClient
from app.schemas import AttachmentResponse, ChatRequest, ConversationResponse, LoginRequest, MessageResponse
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
    app.state.storage.mark_incomplete_generations_failed()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    storage = Storage(settings.database_path)
    ollama_client = OllamaClient(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
    )
    generation_manager = GenerationManager(storage=storage, ollama=ollama_client)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.settings = settings
    app.state.storage = storage
    app.state.ollama = ollama_client
    app.state.generation_manager = generation_manager

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
        "/api/models",
        dependencies=[Depends(require_authenticated_user)],
    )
    async def list_models(request: Request) -> dict[str, object]:
        try:
            models = await request.app.state.ollama.list_models()
        except (httpx.HTTPError, ValueError):
            models = []
        return {"models": models, "default": settings.ollama_model}

    @app.post(
        "/api/upload",
        dependencies=[Depends(require_authenticated_user)],
        response_model=AttachmentResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_file(file: UploadFile, request: Request) -> dict[str, object]:
        storage: Storage = request.app.state.storage
        data = await file.read()

        if len(data) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size is {settings.max_upload_bytes // (1024 * 1024)} MB.",
            )

        content_type = file.content_type or guess_content_type(file.filename or "")
        if not is_allowed(content_type):
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type: {content_type}.",
            )

        filename = file.filename or "upload"
        _, file_path = save_upload(data, filename, settings.upload_dir)
        attachment_id = storage.create_attachment(filename, content_type, file_path)
        attachment = storage.get_attachment(attachment_id)
        return attachment  # type: ignore[return-value]

    @app.get(
        "/api/attachments/{attachment_id}",
        dependencies=[Depends(require_authenticated_user)],
    )
    async def get_attachment_file(attachment_id: int, request: Request) -> FileResponse:
        storage: Storage = request.app.state.storage
        attachment = storage.get_attachment(attachment_id)
        if attachment is None:
            raise HTTPException(status_code=404, detail="Attachment not found.")
        return FileResponse(
            attachment["file_path"],
            media_type=attachment["content_type"],
            filename=attachment["filename"],
        )

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
        generation_manager: GenerationManager = request.app.state.generation_manager
        settings: Settings = request.app.state.settings
        request_id = payload.request_id or uuid4().hex

        generation_job = storage.get_generation_job(request_id)
        if generation_job is None:
            conversation_id = payload.conversation_id
            conversation_model: str | None = None
            if conversation_id is None:
                conversation_model = payload.model or settings.ollama_model
                conversation_id = storage.create_conversation(
                    build_conversation_title(payload.prompt),
                    model=conversation_model,
                )
            else:
                conversation = storage.get_conversation(conversation_id)
                if conversation is None:
                    raise HTTPException(status_code=404, detail="Conversation not found.")
                conversation_model = conversation.get("model") or payload.model or settings.ollama_model
                if conversation.get("model") != conversation_model:
                    storage.update_conversation_model(conversation_id, conversation_model)

            user_message_id = storage.add_message(conversation_id, "user", payload.prompt)
            if payload.attachment_ids:
                storage.link_attachments_to_message(payload.attachment_ids, user_message_id)
            assistant_message_id = storage.add_message(
                conversation_id,
                "assistant",
                "",
                status="pending",
            )
            storage.create_generation_job(
                request_id,
                conversation_id,
                user_message_id,
                assistant_message_id,
            )
            model_messages = storage.get_model_messages(
                conversation_id,
                before_message_id=assistant_message_id,
            )
            generation_manager.start(
                request_id=request_id,
                assistant_message_id=assistant_message_id,
                model_messages=model_messages,
                model=conversation_model,
                attachment_ids=payload.attachment_ids,
            )
            generation_job = storage.get_generation_job(request_id)

        if generation_job is None:
            raise HTTPException(status_code=500, detail="Unable to start generation.")

        conversation = storage.get_conversation(generation_job["conversation_id"])
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found.")

        assistant_message_id = int(generation_job["assistant_message_id"])

        async def event_stream() -> AsyncIterator[str]:
            yield _sse_message(
                "conversation",
                {
                    "conversation_id": generation_job["conversation_id"],
                    "assistant_message_id": assistant_message_id,
                    "request_id": request_id,
                    "title": conversation["title"],
                },
            )

            sent_length = 0
            while True:
                message = storage.get_message(assistant_message_id)
                if message is None:
                    yield _sse_message(
                        "error",
                        {"detail": "Assistant message no longer exists."},
                    )
                    return

                content = message["content"]
                if len(content) > sent_length:
                    chunk = content[sent_length:]
                    sent_length = len(content)
                    yield _sse_message("chunk", {"content": chunk})

                if message["status"] == "completed":
                    yield _sse_message(
                        "done",
                        {
                            "assistant_message_id": assistant_message_id,
                            "conversation_id": generation_job["conversation_id"],
                            "request_id": request_id,
                        },
                    )
                    return

                if message["status"] == "failed":
                    yield _sse_message(
                        "error",
                        {
                            "assistant_message_id": assistant_message_id,
                            "conversation_id": generation_job["conversation_id"],
                            "detail": message["error"] or "Generation failed.",
                            "request_id": request_id,
                        },
                    )
                    return

                await asyncio.sleep(0.25)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.delete(
        "/api/conversations/{conversation_id}",
        dependencies=[Depends(require_authenticated_user)],
        response_class=Response,
    )
    async def delete_conversation(conversation_id: int, request: Request) -> Response:
        storage: Storage = request.app.state.storage
        if not storage.delete_conversation(conversation_id):
            raise HTTPException(status_code=404, detail="Conversation not found.")
        return Response(status_code=204)

    return app


def _sse_message(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


app = create_app()
