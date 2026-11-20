"""Register the evidence services' Speakr API token(s) in Speakr's database.

Runs INSIDE the pinned Speakr container (`podman exec -i speakr python -c`),
so it uses Speakr's own interpreter, SQLAlchemy, and SQLALCHEMY_DATABASE_URI.
The request arrives as JSON on stdin; secret values never appear in argv,
the environment, the Nix store, or this script's output.

Speakr keeps API tokens only in its own database (`api_token`, keyed by the
SHA-256 hex digest of the plaintext, see Speakr's
src/utils/token_auth.py:hash_token). A fresh or replaced Speakr volume
therefore silently invalidates EVIDENCE_SPEAKR_API_TOKEN: every upload gets
HTTP 401. This makes the configured token(s) exist again, idempotently.

The SQL below targets the schema of the digest-pinned Speakr image that
containers.nix asserts on; nix/speakr-provision-schema.sql is a verbatim
copy used by the tests.

Exit codes: 0 reconciled, 75 Speakr not ready yet (caller retries),
1 needs an operator (e.g. the token was revoked in Speakr).
"""

import hashlib
import json
import os
import sys
from datetime import datetime

EX_TEMPFAIL = 75
DEFAULT_DATABASE_URI = "sqlite:////data/instance/transcriptions.db"
TOKEN_NAME = "ai-coaching evidence services (managed by NixOS)"


class NotReady(Exception):
    """Speakr has not finished first-boot initialisation; retry later."""


class ProvisionError(Exception):
    """A state the module must not paper over; needs an operator."""


def log(message):
    print(f"[speakr-provision] {message}", flush=True)


def hash_token(token):
    # Must match Speakr's src/utils/token_auth.py:hash_token.
    return hashlib.sha256(token.encode()).hexdigest()


def utcnow():
    # Speakr stores naive UTC (`default=datetime.utcnow`).
    return datetime.utcnow()


def _resolve_user(conn, text, wanted, admin_username):
    def by_name(name):
        return conn.execute(
            text('SELECT id, username FROM "user" WHERE username = :name'),
            {"name": name},
        ).first()

    if wanted:
        row = by_name(wanted)
        if row is None:
            raise NotReady(f"Speakr user {wanted!r} does not exist yet")
        return row
    if admin_username:
        row = by_name(admin_username)
        if row is not None:
            return row
    row = conn.execute(
        text('SELECT id, username FROM "user" WHERE is_admin ORDER BY id LIMIT 1')
    ).first()
    if row is None:
        raise NotReady("Speakr has no admin user yet")
    return row


def _check_insertable(inspector, table, supplied):
    """Refuse to insert if Speakr's schema grew a required column we do not
    fill (e.g. after an image upgrade), instead of failing obscurely."""
    primary_key = set(
        inspector.get_pk_constraint(table).get("constrained_columns") or []
    )
    missing = [
        column["name"]
        for column in inspector.get_columns(table)
        if not column["nullable"]
        and column.get("default") is None
        and column["name"] not in primary_key
        and column["name"] not in supplied
    ]
    if missing:
        raise ProvisionError(
            f"Speakr's {table} table has required columns this module does not "
            f"know how to fill: {', '.join(missing)}; update nix/speakr-provision.py "
            "for the new Speakr schema"
        )


def reconcile(engine, request, admin_username=None, now=None):
    """Ensure every requested token is a valid Speakr API token.

    Returns the number of tokens registered. Raises NotReady while Speakr is
    still initialising, ProvisionError for states needing an operator.
    """
    from sqlalchemy import Boolean, DateTime, Integer, inspect, text
    from sqlalchemy.sql import bindparam

    now = now or utcnow()
    inspector = inspect(engine)
    missing = [t for t in ("user", "api_token") if not inspector.has_table(t)]
    if missing:
        raise NotReady(
            f"Speakr has not created its schema yet (missing: {', '.join(missing)})"
        )
    tokens = request.get("tokens") or []
    if not tokens:
        raise ProvisionError("no API tokens were supplied")

    insert_columns = (
        "user_id",
        "token_hash",
        "name",
        "created_at",
        "last_used_at",
        "expires_at",
        "revoked",
    )
    _check_insertable(inspector, "api_token", insert_columns)
    lookup = text(
        "SELECT id, user_id, revoked, expires_at FROM api_token "
        "WHERE token_hash = :token_hash"
    ).columns(id=Integer, user_id=Integer, revoked=Boolean, expires_at=DateTime)
    insert = text(
        f"INSERT INTO api_token ({', '.join(insert_columns)}) VALUES "
        "(:user_id, :token_hash, :name, :created_at, NULL, NULL, :revoked)"
    ).bindparams(
        bindparam("created_at", type_=DateTime()),
        bindparam("revoked", type_=Boolean()),
    )

    registered = 0
    errors = []
    with engine.begin() as conn:
        user = _resolve_user(conn, text, request.get("user"), admin_username)
        for token in tokens:
            label = token.get("label") or "configured token"
            digest = hash_token(token["value"])
            row = conn.execute(lookup, {"token_hash": digest}).first()
            if row is None:
                conn.execute(
                    insert,
                    {
                        "user_id": user.id,
                        "token_hash": digest,
                        "name": TOKEN_NAME,
                        "created_at": now,
                        "revoked": False,
                    },
                )
                registered += 1
                log(
                    f"Speakr did not know the API token from {label}; "
                    f"registered it for Speakr user {user.username!r}"
                )
            elif row.revoked:
                errors.append(
                    f"the API token from {label} is revoked in Speakr; rotate "
                    "EVIDENCE_SPEAKR_API_TOKEN (a revoked token is never re-enabled)"
                )
            elif row.expires_at is not None and row.expires_at < now:
                errors.append(
                    f"the API token from {label} expired in Speakr at "
                    f"{row.expires_at.isoformat()}; rotate EVIDENCE_SPEAKR_API_TOKEN"
                )
            else:
                log(f"the API token from {label} is already registered in Speakr")
    if errors:
        raise ProvisionError("; ".join(errors))
    return registered


def _sqlite_file_missing(url):
    # Connecting to a missing SQLite file would create an empty one that
    # Speakr then adopts; wait for Speakr to create it instead.
    return (
        url.get_backend_name() == "sqlite"
        and url.database not in (None, "", ":memory:")
        and not os.path.exists(url.database)
    )


def main():
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import OperationalError

    request = json.load(sys.stdin)
    url = make_url(os.environ.get("SQLALCHEMY_DATABASE_URI", DEFAULT_DATABASE_URI))
    if _sqlite_file_missing(url):
        log("not ready: Speakr has not created its database yet")
        return EX_TEMPFAIL
    connect_args = {"timeout": 30} if url.get_backend_name() == "sqlite" else {}
    # hide_parameters keeps token hashes out of any SQLAlchemy error text.
    engine = create_engine(url, connect_args=connect_args, hide_parameters=True)
    try:
        reconcile(engine, request, admin_username=os.environ.get("ADMIN_USERNAME"))
    except NotReady as exc:
        log(f"not ready: {exc}")
        return EX_TEMPFAIL
    except OperationalError as exc:
        log(f"not ready: database unavailable ({type(exc.orig).__name__})")
        return EX_TEMPFAIL
    except ProvisionError as exc:
        log(f"ERROR: {exc}")
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
