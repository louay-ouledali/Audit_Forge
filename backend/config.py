from __future__ import annotations

import secrets
from pathlib import Path

from pydantic_settings import BaseSettings

from backend.frozen_paths import BUNDLE_DIR, DATA_ROOT, DB_DIR, ENV_FILE

PROJECT_ROOT = DATA_ROOT  # writable root — used for benchmarks, reports, data


def _generate_secret_key() -> str:
    """Generate a persistent secret key and store it in .env.

    On first run (no SECRET_KEY in env or .env), writes a random
    256-bit key to `.env` so the same key is used on subsequent starts.
    """
    env_path = ENV_FILE
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("SECRET_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    key = secrets.token_urlsafe(32)
    # Append to .env so it persists across restarts
    with open(env_path, "a", encoding="utf-8") as f:
        f.write(f"\nSECRET_KEY={key}\n")
    return key


class Settings(BaseSettings):
    SECRET_KEY: str = _generate_secret_key()
    JWT_SECRET_KEY: str = ""  # If empty, derived from SECRET_KEY
    ENCRYPTION_KEY: str = ""  # If empty, derived from SECRET_KEY
    APP_ENV: str = "development"
    DATABASE_URL: str = f"sqlite:///{DB_DIR / 'auditforge.db'}"
    SERVER_PORT: str = "8000"
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    LLM_OLLAMA_URL: str = "http://host.docker.internal:11434"

    model_config = {"env_file": str(ENV_FILE), "env_file_encoding": "utf-8"}

    @property
    def resolved_database_url(self) -> str:
        """Resolve relative sqlite paths against DATA_ROOT."""
        url = self.DATABASE_URL
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            rel_path = url.replace("sqlite:///", "")
            abs_path = DATA_ROOT / rel_path
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{abs_path}"
        return url

    @property
    def effective_jwt_key(self) -> str:
        """Return the key used for JWT signing."""
        return self.JWT_SECRET_KEY if self.JWT_SECRET_KEY else self.SECRET_KEY

    @property
    def effective_encryption_key(self) -> str:
        """Return the key used for Fernet encryption."""
        return self.ENCRYPTION_KEY if self.ENCRYPTION_KEY else self.SECRET_KEY


settings = Settings()
