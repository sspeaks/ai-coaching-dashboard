from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    Engine,
    Integer,
    MetaData,
    String,
    Table,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import Connection
from sqlalchemy.schema import CreateColumn

from .db import Base


Migration = tuple[int, str, Callable[[Connection], None]]

_migration_metadata = MetaData()
_schema_migration = Table(
    "schema_migration",
    _migration_metadata,
    Column("version", Integer, primary_key=True),
    Column("name", String(255), nullable=False),
    Column("applied_at", DateTime(timezone=True), nullable=False),
)


def _initial_schema(connection: Connection) -> None:
    from .models import SessionRecord

    if SessionRecord.metadata is not Base.metadata:
        raise RuntimeError("model metadata is not registered on the database base")
    Base.metadata.create_all(connection)


def _worker_safety_schema(connection: Connection) -> None:
    from .models import DeletionCompensationRecord, DeletionTombstoneRecord

    _add_column(
        connection,
        "coaching_session",
        Column("pending_operation_kind", String(32)),
    )
    _add_column(
        connection,
        "coaching_session",
        Column("pending_operation_id", String(36)),
    )
    _add_column(
        connection,
        "coaching_session",
        Column("pending_operation_started_at", DateTime(timezone=True)),
    )
    _add_version_column(connection, "coaching_session")
    _add_version_column(connection, "evidence_job")

    DeletionTombstoneRecord.__table__.create(connection, checkfirst=True)
    _add_column(
        connection,
        "deletion_tombstone",
        Column("compensated_recording_id", String(100)),
    )
    _add_column(
        connection,
        "deletion_tombstone",
        Column("compensated_at", DateTime(timezone=True)),
    )
    DeletionCompensationRecord.__table__.create(connection, checkfirst=True)


def _operation_resolution_schema(connection: Connection) -> None:
    from .models import ProviderOperationResolutionRecord

    _add_column(
        connection,
        "evidence_job",
        Column("ambiguous_operation_id", String(36)),
    )
    ProviderOperationResolutionRecord.__table__.create(connection, checkfirst=True)
    connection.execute(
        text(
            """
            UPDATE evidence_job
            SET ambiguous_operation_id = (
                SELECT coaching_session.pending_operation_id
                FROM coaching_session
                WHERE coaching_session.id = evidence_job.session_id
            )
            WHERE error_code = :error_code
              AND ambiguous_operation_id IS NULL
            """
        ),
        {"error_code": "ambiguous_provider_operation"},
    )


MIGRATIONS: tuple[Migration, ...] = (
    (1, "initial_schema", _initial_schema),
    (2, "worker_safety_schema", _worker_safety_schema),
    (3, "operation_resolution_audit", _operation_resolution_schema),
)


def run_migrations(engine: Engine) -> None:
    """Apply all schema migrations under a deployment-safe database lock."""

    with engine.connect() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            connection.begin()
            if connection.dialect.name == "postgresql":
                connection.exec_driver_sql(
                    "SELECT pg_advisory_xact_lock(1447636041)"
                )
        try:
            _schema_migration.create(connection, checkfirst=True)
            applied = set(
                connection.scalars(select(_schema_migration.c.version))
            )
            for version, name, migration in MIGRATIONS:
                if version in applied:
                    continue
                migration(connection)
                connection.execute(
                    _schema_migration.insert().values(
                        version=version,
                        name=name,
                        applied_at=datetime.now(UTC),
                    )
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def _add_version_column(connection: Connection, table_name: str) -> None:
    _add_column(
        connection,
        table_name,
        Column(
            "version",
            Integer,
            nullable=False,
            server_default=text("1"),
        ),
    )
    table = _quote(connection, table_name)
    version = _quote(connection, "version")
    connection.exec_driver_sql(
        f"UPDATE {table} SET {version} = 1 WHERE {version} IS NULL"
    )
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            f"ALTER TABLE {table} ALTER COLUMN {version} SET DEFAULT 1"
        )
        connection.exec_driver_sql(
            f"ALTER TABLE {table} ALTER COLUMN {version} SET NOT NULL"
        )


def _add_column(
    connection: Connection,
    table_name: str,
    column: Column,
) -> None:
    inspector = inspect(connection)
    if table_name not in inspector.get_table_names():
        return
    if column.name in {
        existing["name"] for existing in inspector.get_columns(table_name)
    }:
        return
    table = _quote(connection, table_name)
    definition = str(
        CreateColumn(column).compile(dialect=connection.dialect)
    )
    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _quote(connection: Connection, identifier: str) -> str:
    return connection.dialect.identifier_preparer.quote(identifier)
