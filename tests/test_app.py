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


def test_login_flow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    client = create_test_client(tmp_path)

    login_response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "password"},
    )
    assert login_response.status_code == 200
    assert login_response.json() == {"authenticated": True}

    auth_response = client.get("/api/auth/me")
    assert auth_response.status_code == 200
    assert auth_response.json() == {"authenticated": True}


def test_requires_auth_for_conversations(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    client = create_test_client(tmp_path)

    response = client.get("/api/conversations")
    assert response.status_code == 401
