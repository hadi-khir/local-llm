from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Local LLM"
    secret_key: str = Field(..., alias="SECRET_KEY")
    admin_username: str = Field(..., alias="ADMIN_USERNAME")
    admin_password: str = Field(..., alias="ADMIN_PASSWORD")
    session_cookie_name: str = Field("local_llm_session", alias="SESSION_COOKIE_NAME")
    session_cookie_secure: bool = Field(True, alias="SESSION_COOKIE_SECURE")
    ollama_base_url: str = Field(..., alias="OLLAMA_BASE_URL")
    ollama_model: str = Field("qwen2.5:3b-instruct", alias="OLLAMA_MODEL")
    database_path: Path = Field(Path("app.db"), alias="DATABASE_PATH")
    upload_dir: Path = Field(Path("/data/uploads"), alias="UPLOAD_DIR")
    max_upload_bytes: int = Field(20 * 1024 * 1024, alias="MAX_UPLOAD_BYTES")
    host: str = Field("0.0.0.0", alias="HOST")
    port: int = Field(8000, alias="PORT")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
