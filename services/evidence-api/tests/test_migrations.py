import sqlite3
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from evidence_api.app import create_app
from evidence_api.config import Settings
from evidence_api.db import (
    create_db_engine,
    create_session_factory,
    init_schema,
)
from evidence_api.models import JobRecord, SessionRecord


def _create_pre_change_database(path: Path) -> tuple[str, str]:
    session_id = "legacy-session"
    job_id = "legacy-job"
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(path) as database:
        database.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE coaching_session (
                id VARCHAR(36) PRIMARY KEY,
                title VARCHAR(300) NOT NULL,
                state VARCHAR(32) NOT NULL,
                recorded_at DATETIME,
                duration_ms BIGINT,
                notes TEXT,
                original_filename VARCHAR(500),
                media_path TEXT,
                media_sha256 VARCHAR(64),
                media_size_bytes BIGINT,
                speakr_recording_id VARCHAR(100),
                transcription_submitted_at DATETIME,
                current_transcript_revision_id VARCHAR(36),
                last_reconciled_at DATETIME,
                last_error TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            CREATE TABLE evidence_job (
                id VARCHAR(36) PRIMARY KEY,
                session_id VARCHAR(36) NOT NULL
                    REFERENCES coaching_session(id) ON DELETE CASCADE,
                type VARCHAR(32) NOT NULL,
                status VARCHAR(32) NOT NULL,
                attempts INTEGER NOT NULL,
                max_attempts INTEGER NOT NULL,
                error_code VARCHAR(100),
                error_message TEXT,
                available_at DATETIME NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            CREATE TABLE deletion_tombstone (
                session_id VARCHAR(36) PRIMARY KEY,
                requested_at DATETIME NOT NULL
            );
            """
        )
        database.execute(
            """
            INSERT INTO coaching_session (
                id, title, state, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, "Legacy session", "TRANSCRIBING", now, now),
        )
        database.execute(
            """
            INSERT INTO evidence_job (
                id, session_id, type, status, attempts, max_attempts,
                available_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                session_id,
                "TRANSCRIBE",
                "FAILED",
                1,
                3,
                now,
                now,
                now,
            ),
        )
        database.execute(
            """
            INSERT INTO deletion_tombstone (session_id, requested_at)
            VALUES (?, ?)
            """,
            ("deleted-legacy-session", now),
        )
        database.commit()
    return session_id, job_id


def _settings(path: Path) -> Settings:
    return Settings(
        environment="test",
        auth_mode="development",
        database_url=f"sqlite:///{path}",
        media_root=path.parent / "media",
    )


def _runtime(name: str) -> Path:
    root = Path("services/evidence-api/tests/.runtime-migrations") / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return root


def test_migrations_upgrade_pre_change_database_idempotently():
    database_path = _runtime("upgrade") / "legacy.db"
    session_id, job_id = _create_pre_change_database(database_path)
    engine = create_db_engine(_settings(database_path))

    init_schema(engine)
    init_schema(engine)

    inspector = inspect(engine)
    session_columns = {
        column["name"] for column in inspector.get_columns("coaching_session")
    }
    job_columns = {
        column["name"] for column in inspector.get_columns("evidence_job")
    }
    tombstone_columns = {
        column["name"] for column in inspector.get_columns("deletion_tombstone")
    }
    compensation_columns = {
        column["name"]
        for column in inspector.get_columns("deletion_compensation")
    }
    assert {
        "version",
        "pending_operation_kind",
        "pending_operation_id",
        "pending_operation_started_at",
    } <= session_columns
    assert {"version", "ambiguous_operation_id"} <= job_columns
    assert {"compensated_recording_id", "compensated_at"} <= tombstone_columns
    assert {
        "recording_id",
        "status",
        "attempts",
        "error_code",
        "error_message",
        "available_at",
        "completed_at",
    } <= compensation_columns
    assert {
        "deletion_compensation",
        "provider_operation_resolution",
        "schema_migration",
        "session_summary",
    } <= set(inspector.get_table_names())

    factory = create_session_factory(engine)
    with factory() as db:
        session = db.get(SessionRecord, session_id)
        job = db.get(JobRecord, job_id)
        assert session.version == 1
        assert job.version == 1
        assert session.pending_operation_kind is None
        session.notes = "migration write succeeds"
        db.commit()
        assert session.version == 2
        versions = list(
            db.scalars(text("SELECT version FROM schema_migration ORDER BY version"))
        )
        assert versions == [1, 2, 3, 4]


def test_api_startup_migrates_legacy_database_before_orm_queries():
    database_path = _runtime("startup") / "startup-legacy.db"
    session_id, _ = _create_pre_change_database(database_path)
    app = create_app(_settings(database_path))

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.get(f"/api/sessions/{session_id}")

    assert response.status_code == 200
    assert response.json()["title"] == "Legacy session"
