"""phase1_restructure: targets→clients, mission locking, finding overrides, saved reports

Revision ID: d5a1b2c3e4f5
Revises: c4d5e6f7a8b9
Create Date: 2025-01-15 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d5a1b2c3e4f5"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def _has_column(conn, table: str, column: str) -> bool:
    """Check if a column exists in a table (SQLite)."""
    result = conn.execute(sa.text(f"PRAGMA table_info({table})"))
    return any(row[1] == column for row in result)


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. Create new tables (if not already created by init_db) ──
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS mission_targets (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            mission_id INTEGER NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
            target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
            added_at DATETIME
        )
    """))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_mission_targets_mission_id ON mission_targets (mission_id)"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_mission_targets_target_id ON mission_targets (target_id)"))

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS saved_reports (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            mission_id INTEGER,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            scope VARCHAR(50),
            scope_id INTEGER,
            scan_ids_json TEXT,
            config_json TEXT,
            format VARCHAR(10) NOT NULL DEFAULT 'html',
            generated_blob BLOB,
            file_size_kb FLOAT,
            ai_enhanced VARCHAR(20) DEFAULT 'none',
            ai_enhanced_at DATETIME,
            status VARCHAR(20) DEFAULT 'draft',
            generated_at DATETIME,
            created_at DATETIME,
            updated_at DATETIME
        )
    """))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_saved_reports_mission_id ON saved_reports (mission_id)"))

    # ── 2. Add columns to missions (locking) ─────────────────
    if not _has_column(conn, "missions", "is_locked"):
        conn.execute(sa.text("ALTER TABLE missions ADD COLUMN is_locked BOOLEAN DEFAULT 0"))
    if not _has_column(conn, "missions", "password_hash"):
        conn.execute(sa.text("ALTER TABLE missions ADD COLUMN password_hash VARCHAR"))
    if not _has_column(conn, "missions", "locked_at"):
        conn.execute(sa.text("ALTER TABLE missions ADD COLUMN locked_at DATETIME"))
    if not _has_column(conn, "missions", "locked_by"):
        conn.execute(sa.text("ALTER TABLE missions ADD COLUMN locked_by VARCHAR"))

    # ── 3. Add override columns to findings ───────────────────
    if not _has_column(conn, "findings", "auditor_status_override"):
        conn.execute(sa.text("ALTER TABLE findings ADD COLUMN auditor_status_override VARCHAR"))
    if not _has_column(conn, "findings", "auditor_severity_override"):
        conn.execute(sa.text("ALTER TABLE findings ADD COLUMN auditor_severity_override VARCHAR"))
    if not _has_column(conn, "findings", "auditor_description"):
        conn.execute(sa.text("ALTER TABLE findings ADD COLUMN auditor_description TEXT"))
    if not _has_column(conn, "findings", "auditor_remediation"):
        conn.execute(sa.text("ALTER TABLE findings ADD COLUMN auditor_remediation TEXT"))
    if not _has_column(conn, "findings", "override_reason"):
        conn.execute(sa.text("ALTER TABLE findings ADD COLUMN override_reason TEXT"))
    if not _has_column(conn, "findings", "overridden_at"):
        conn.execute(sa.text("ALTER TABLE findings ADD COLUMN overridden_at DATETIME"))

    # ── 4. Add mission_id to scans ────────────────────────────
    if not _has_column(conn, "scans", "mission_id"):
        conn.execute(sa.text("ALTER TABLE scans ADD COLUMN mission_id INTEGER REFERENCES missions(id) ON DELETE SET NULL"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_scans_mission_id ON scans (mission_id)"))

    # ── 5. Migrate targets: mission_id → client_id ────────────
    #
    # SQLite doesn't support DROP COLUMN before 3.35+, so we use
    # batch mode which recreates the table. But first, we populate
    # the junction table and the new client_id column.
    #
    # Step A: Populate mission_targets from existing target.mission_id
    # Step B: Populate scan.mission_id from target.mission_id
    # Step C: Add client_id to targets (via mission → client)
    # Step D: Drop mission_id from targets
    #
    # All done via raw SQL since we need data migration.

    conn = op.get_bind()

    # A: Create mission_target links from existing data (if mission_id still exists)
    if _has_column(conn, "targets", "mission_id"):
        # Only populate if junction table is empty
        count = conn.execute(sa.text("SELECT COUNT(*) FROM mission_targets")).scalar()
        if count == 0:
            conn.execute(sa.text("""
                INSERT INTO mission_targets (mission_id, target_id, added_at)
                SELECT mission_id, id, CURRENT_TIMESTAMP
                FROM targets
                WHERE mission_id IS NOT NULL
            """))

        # B: Set scan.mission_id from target → mission link
        conn.execute(sa.text("""
            UPDATE scans
            SET mission_id = (
                SELECT t.mission_id FROM targets t WHERE t.id = scans.target_id
            )
            WHERE scans.mission_id IS NULL
        """))

        # C: Add client_id column to targets, set from mission.client_id
        if not _has_column(conn, "targets", "client_id"):
            conn.execute(sa.text("ALTER TABLE targets ADD COLUMN client_id INTEGER"))

        conn.execute(sa.text("""
            UPDATE targets
            SET client_id = (
                SELECT m.client_id FROM missions m WHERE m.id = targets.mission_id
            )
            WHERE targets.client_id IS NULL AND targets.mission_id IS NOT NULL
        """))

        # D: Drop mission_id from targets using batch mode (SQLite compat)
        with op.batch_alter_table("targets", schema=None) as batch_op:
            batch_op.drop_column("mission_id")
            batch_op.create_foreign_key(
                "fk_targets_client_id",
                "clients",
                ["client_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch_op.alter_column("client_id", nullable=False)

    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_targets_client_id ON targets (client_id)"))


def downgrade() -> None:
    # Reverse: add mission_id back to targets, drop client_id, etc.
    conn = op.get_bind()

    with op.batch_alter_table("targets") as batch_op:
        batch_op.add_column(sa.Column("mission_id", sa.Integer(), nullable=True))

    # Restore mission_id from junction table (pick first)
    conn.execute(sa.text("""
        UPDATE targets
        SET mission_id = (
            SELECT mt.mission_id FROM mission_targets mt
            WHERE mt.target_id = targets.id
            LIMIT 1
        )
    """))

    with op.batch_alter_table("targets", schema=None) as batch_op:
        batch_op.drop_column("client_id")
        batch_op.create_foreign_key(
            "fk_targets_mission_id",
            "missions",
            ["mission_id"],
            ["id"],
            ondelete="CASCADE",
        )

    op.drop_index("ix_targets_client_id", "targets")
    op.drop_index("ix_scans_mission_id", "scans")

    with op.batch_alter_table("scans") as batch_op:
        batch_op.drop_column("mission_id")

    with op.batch_alter_table("findings") as batch_op:
        batch_op.drop_column("auditor_status_override")
        batch_op.drop_column("auditor_severity_override")
        batch_op.drop_column("auditor_description")
        batch_op.drop_column("auditor_remediation")
        batch_op.drop_column("override_reason")
        batch_op.drop_column("overridden_at")

    with op.batch_alter_table("missions") as batch_op:
        batch_op.drop_column("is_locked")
        batch_op.drop_column("password_hash")
        batch_op.drop_column("locked_at")
        batch_op.drop_column("locked_by")

    op.drop_table("saved_reports")
    op.drop_index("ix_saved_reports_mission_id", "saved_reports")
    op.drop_table("mission_targets")
    op.drop_index("ix_mission_targets_mission_id", "mission_targets")
    op.drop_index("ix_mission_targets_target_id", "mission_targets")
