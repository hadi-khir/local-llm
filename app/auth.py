from hmac import compare_digest

from fastapi import HTTPException, Request, status

from app.config import Settings


def require_authenticated_user(request: Request) -> None:
    if not request.session.get("authenticated"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )


def authenticate_user(settings: Settings, username: str, password: str) -> bool:
    return compare_digest(username, settings.admin_username) and compare_digest(
        password, settings.admin_password
    )
