from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class Target(Base):
    __tablename__ = "targets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Targets now belong to a CLIENT (not a mission)
    client_id = Column(Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    hostname = Column(String)
    ip_address = Column(String)
    mac_address = Column(String, nullable=True, index=True)  # persistent hardware ID
    target_type = Column(String, nullable=False)
    os_details = Column(String)
    connection_method = Column(String)

    ssh_username = Column(String)
    ssh_key_path = Column(String)
    ssh_password_encrypted = Column(Text)
    port = Column(Integer)
    db_connection_string_encrypted = Column(Text)

    notes = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # ── Phase 1 — Scanning Enhancement Fields ────────────────
    # Platform sub-type for more specific connector/benchmark matching
    # e.g. "cisco_ios", "ubuntu", "server_2022", "postgresql", …
    platform_subtype = Column(String, nullable=True)

    # Default benchmark to use when scanning this target
    default_benchmark_id = Column(
        Integer,
        ForeignKey("benchmarks.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Connection health tracking
    last_connection_test = Column(DateTime, nullable=True)
    connection_status = Column(String, nullable=True)   # "ok" | "failed" | "untested"
    connection_error = Column(Text, nullable=True)

    # Database-specific fields
    db_name = Column(String, nullable=True)       # default database name
    db_instance = Column(String, nullable=True)    # MSSQL named instance

    # Network device specific
    enable_password_encrypted = Column(Text, nullable=True)  # enable/privilege password
    device_type = Column(String, nullable=True)              # netmiko device_type string

    # TLS verification (default True — verify server certificates)
    verify_tls = Column(Boolean, nullable=False, server_default="1")

    # Config audit
    config_pull_method = Column(String, nullable=True)  # "auto" | "upload_only" | "disabled"
    latest_config_id = Column(
        Integer,
        ForeignKey("config_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    client = relationship("Client", back_populates="targets")
    default_benchmark = relationship("Benchmark", foreign_keys=[default_benchmark_id])
    scans = relationship("Scan", back_populates="target", cascade="all, delete-orphan")
    # Many-to-many with missions via junction table
    missions = relationship(
        "Mission",
        secondary="mission_targets",
        back_populates="targets",
    )
    config_snapshots = relationship(
        "ConfigSnapshot", back_populates="target",
        foreign_keys="ConfigSnapshot.target_id",
        cascade="all, delete-orphan",
    )
    latest_config = relationship(
        "ConfigSnapshot", foreign_keys=[latest_config_id], post_update=True,
    )
