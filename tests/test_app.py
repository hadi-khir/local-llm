import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient


def create_test_client(tmp_path: Path) -> TestClient:
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    app.state.settings.database_path = tmp_path / "test.db"
    app.state.storage.database_path = app.state.settings.database_path
    return TestClient(app)


def login(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "password"},
    )
    assert response.status_code == 200


def test_login_flow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b-instruct")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")

    with create_test_client(tmp_path) as client:
        login(client)
        auth_response = client.get("/api/auth/me")
        assert auth_response.status_code == 200
        assert auth_response.json() == {"authenticated": True}


def test_requires_auth_for_conversations(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b-instruct")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")

    with create_test_client(tmp_path) as client:
        response = client.get("/api/conversations")
        assert response.status_code == 401


def test_chat_completes_and_persists_messages(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b-instruct")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")

    with create_test_client(tmp_path) as client:
        login(client)

        async def fake_stream_chat(_messages, model=None, images=None):
            assert model == "qwen2.5:3b-instruct"
            assert images is None
            yield "Hello"
            await asyncio.sleep(0.01)
            yield " world"

        client.app.state.ollama.stream_chat = fake_stream_chat

        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"prompt": "Say hello", "request_id": "req-hello"},
        ) as response:
            body = "".join(response.iter_text())
            assert response.status_code == 200
        assert "event: done" in body

        conversations = client.get("/api/conversations").json()
        messages = client.get(f"/api/conversations/{conversations[0]['id']}/messages").json()
        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert messages[1]["content"] == "Hello world"
        assert messages[1]["status"] == "completed"


def test_generation_survives_stream_disconnect(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b-instruct")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")

    with create_test_client(tmp_path) as client:
        login(client)

        async def fake_stream_chat(_messages, model=None, images=None):
            assert model == "qwen2.5:3b-instruct"
            assert images is None
            yield "Partial"
            await asyncio.sleep(0.05)
            yield " response"

        client.app.state.ollama.stream_chat = fake_stream_chat

        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"prompt": "Keep going", "request_id": "req-background"},
        ) as response:
            first_event = next(response.iter_text())
            assert "event: conversation" in first_event

        time.sleep(0.15)

        conversations = client.get("/api/conversations").json()
        messages = client.get(f"/api/conversations/{conversations[0]['id']}/messages").json()
        assert messages[-1]["role"] == "assistant"
        assert messages[-1]["content"] == "Partial response"
        assert messages[-1]["status"] == "completed"


def test_new_conversation_persists_selected_model(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("OLLAMA_MODEL", "default-model")

    used_models: list[str | None] = []

    with create_test_client(tmp_path) as client:
        login(client)

        async def fake_stream_chat(_messages, model=None, images=None):
            used_models.append(model)
            assert images is None
            yield "Locked"

        client.app.state.ollama.stream_chat = fake_stream_chat

        with client.stream(
            "POST",
            "/api/chat/stream",
            json={
                "prompt": "Use another model",
                "request_id": "req-model-lock",
                "model": "llama3.1:8b",
            },
        ) as response:
            body = "".join(response.iter_text())
            assert response.status_code == 200
        assert "event: done" in body
        conversations = client.get("/api/conversations").json()
        assert conversations[0]["model"] == "llama3.1:8b"
        assert used_models == ["llama3.1:8b"]


def test_existing_conversation_keeps_original_model(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("OLLAMA_MODEL", "default-model")

    used_models: list[str | None] = []

    with create_test_client(tmp_path) as client:
        login(client)

        async def fake_stream_chat(_messages, model=None, images=None):
            used_models.append(model)
            assert images is None
            yield "OK"

        client.app.state.ollama.stream_chat = fake_stream_chat

        with client.stream(
            "POST",
            "/api/chat/stream",
            json={
                "prompt": "First turn",
                "request_id": "req-first-model",
                "model": "llama3.1:8b",
            },
        ) as first:
            first_body = "".join(first.iter_text())
            assert first.status_code == 200
        assert "event: done" in first_body

        conversations = client.get("/api/conversations").json()
        conversation_id = conversations[0]["id"]

        with client.stream(
            "POST",
            "/api/chat/stream",
            json={
                "prompt": "Second turn",
                "conversation_id": conversation_id,
                "request_id": "req-second-model",
                "model": "mistral:latest",
            },
        ) as second:
            second_body = "".join(second.iter_text())
            assert second.status_code == 200
        assert "event: done" in second_body

        conversations = client.get("/api/conversations").json()
        assert conversations[0]["model"] == "llama3.1:8b"
        assert used_models == ["llama3.1:8b", "llama3.1:8b"]
