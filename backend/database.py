from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from backend.config import settings

_connect_args: dict = {}
if settings.resolved_database_url.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(
    settings.resolved_database_url,
    connect_args=_connect_args,
)

# Enable WAL mode for SQLite (better concurrent read/write performance)
# NOTE: WAL requires mmap which fails on Windows→Docker bind mounts,
# so fall back to DELETE journal mode when WAL activation fails.
if settings.resolved_database_url.startswith("sqlite"):
    from sqlalchemy import event as _sa_event

    @_sa_event.listens_for(engine, "connect")
    def _set_sqlite_wal(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        # Enable foreign key enforcement — without this, ON DELETE SET NULL
        # and all other FK constraints are silently ignored by SQLite.
        cursor.execute("PRAGMA foreign_keys = ON")
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            # Fallback for environments where WAL is unsupported (e.g. Docker bind mounts)
            cursor.execute("PRAGMA journal_mode=DELETE")
            cursor.execute("PRAGMA synchronous=FULL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

DEFAULT_SETTINGS: list[tuple[str, str]] = [
    ("llm_mode", "offline"),
    ("llm_offline_model", "mistral"),
    ("llm_ollama_url", "http://host.docker.internal:11434"),
    ("llm_online_provider", ""),
    ("llm_online_api_key_encrypted", ""),
    ("llm_online_model", ""),
    ("verification_enabled", "true"),
    ("verification_auto_protect_passing", "false"),
    ("default_scan_mode", "script_export"),
    ("llm_category_detection", "true"),
]


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    import backend.models  # noqa: F401 – ensure all models are registered

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        from backend.models.app_settings import AppSettings

        existing = db.query(AppSettings).count()
        if existing == 0:
            now = datetime.now(timezone.utc)
            for key, value in DEFAULT_SETTINGS:
                db.add(AppSettings(key=key, value=value, updated_at=now))
            db.commit()
    finally:
        db.close()
