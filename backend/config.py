from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    DATABASE_URL: str = "sqlite:///data/auditforge.db"
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:8000"]
    LLM_OLLAMA_URL: str = "http://host.docker.internal:11434"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def resolved_database_url(self) -> str:
        """Resolve relative sqlite paths against the project root."""
        url = self.DATABASE_URL
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            rel_path = url.replace("sqlite:///", "")
            abs_path = PROJECT_ROOT / rel_path
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{abs_path}"
        return url


settings = Settings()
