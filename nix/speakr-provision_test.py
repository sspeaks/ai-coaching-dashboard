import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text


def load(name, env_var):
    spec = importlib.util.spec_from_file_location(name, os.environ[env_var])
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROVISION = load("speakr_provision", "SPEAKR_PROVISION_SOURCE")
RUNNER = load("speakr_provision_runner", "SPEAKR_PROVISION_RUNNER_SOURCE")
SCHEMA = Path(os.environ["SPEAKR_PROVISION_SCHEMA"]).read_text(encoding="utf-8")

TOKEN = "tok_" + "a" * 39
OTHER_TOKEN = "tok_" + "b" * 39
NOW = datetime(2026, 11, 19, 1, 2, 3, 456789)


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


class SpeakrDatabase:
    def __init__(self, root):
        self.path = root / "transcriptions.db"
        self.url = f"sqlite:///{self.path}"
        self.engine = create_engine(self.url)

    def create_schema(self):
        sql = "\n".join(
            line for line in SCHEMA.splitlines() if not line.startswith("--")
        )
        with self.engine.begin() as conn:
            for statement in sql.split(";"):
                if statement.strip():
                    conn.exec_driver_sql(statement)

    def add_user(self, username, is_admin):
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    'INSERT INTO "user" (username, email, is_admin) '
                    "VALUES (:u, :e, :a)"
                ),
                {"u": username, "e": f"{username}@example.invalid", "a": is_admin},
            )

    def add_token(self, token, revoked=False, expires_at=None, user_id=1):
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO api_token (user_id, token_hash, name, created_at, "
                    "expires_at, revoked) VALUES (:uid, :h, 'manual', "
                    "'2026-08-08 16:17:25.229857', :exp, :rev)"
                ),
                {
                    "uid": user_id,
                    "h": digest(token),
                    "exp": expires_at,
                    "rev": revoked,
                },
            )

    def tokens(self):
        with self.engine.connect() as conn:
            return [
                dict(row._mapping)
                for row in conn.execute(
                    text(
                        "SELECT user_id, token_hash, name, created_at, last_used_at, "
                        "expires_at, revoked FROM api_token ORDER BY id"
                    )
                )
            ]


def request(*tokens, user=None):
    return {
        "tokens": [{"value": t, "label": f"file-{i}.env"} for i, t in enumerate(tokens)],
        "user": user,
    }


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / "speakr-provision-runtime"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir()
        self.db = SpeakrDatabase(self.root)

    def tearDown(self):
        self.db.engine.dispose()
        shutil.rmtree(self.root, ignore_errors=True)

    def reconcile(self, req, admin_username="admin"):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = PROVISION.reconcile(
                self.db.engine, req, admin_username=admin_username, now=NOW
            )
        return result, output.getvalue()

    def test_registers_missing_token_like_speakr_would(self):
        self.db.create_schema()
        self.db.add_user("someone", False)
        self.db.add_user("admin", True)

        registered, output = self.reconcile(request(TOKEN))

        self.assertEqual(registered, 1)
        [row] = self.db.tokens()
        self.assertEqual(row["user_id"], 2)
        self.assertEqual(row["token_hash"], digest(TOKEN))
        self.assertEqual(row["name"], PROVISION.TOKEN_NAME)
        # Same text format SQLAlchemy's DateTime writes for Speakr's own rows.
        self.assertEqual(row["created_at"], "2026-11-19 01:02:03.456789")
        self.assertIsNone(row["last_used_at"])
        self.assertIsNone(row["expires_at"])
        self.assertEqual(row["revoked"], 0)
        self.assertIn("registered it for Speakr user 'admin'", output)
        self.assertNotIn(TOKEN, output)
        self.assertNotIn(digest(TOKEN), output)

    def test_is_idempotent_and_keeps_existing_rows(self):
        self.db.create_schema()
        self.db.add_user("admin", True)
        self.db.add_token(TOKEN)

        registered, output = self.reconcile(request(TOKEN, OTHER_TOKEN))
        again, _ = self.reconcile(request(TOKEN, OTHER_TOKEN))

        self.assertEqual((registered, again), (1, 0))
        rows = self.db.tokens()
        self.assertEqual([r["token_hash"] for r in rows], [digest(TOKEN), digest(OTHER_TOKEN)])
        self.assertEqual(rows[0]["name"], "manual")
        self.assertIn("file-0.env is already registered", output)

    def test_user_selection(self):
        self.db.create_schema()
        self.db.add_user("first-admin", True)
        self.db.add_user("chosen", False)
        self.db.add_user("admin", True)

        self.reconcile(request(TOKEN, user="chosen"))
        self.reconcile(request(OTHER_TOKEN), admin_username="renamed-away")

        self.assertEqual([r["user_id"] for r in self.db.tokens()], [2, 1])

    def test_never_revives_revoked_or_expired_tokens(self):
        self.db.create_schema()
        self.db.add_user("admin", True)
        self.db.add_token(TOKEN, revoked=True)
        self.db.add_token(OTHER_TOKEN, expires_at="2026-01-01 00:00:00.000000")
        fresh = "tok_" + "c" * 39

        with self.assertRaises(PROVISION.ProvisionError) as caught:
            self.reconcile(request(TOKEN, OTHER_TOKEN, fresh))

        message = str(caught.exception)
        self.assertIn("file-0.env is revoked", message)
        self.assertIn("file-1.env expired", message)
        self.assertNotIn(TOKEN, message)
        rows = self.db.tokens()
        self.assertEqual(rows[0]["revoked"], 1)
        self.assertEqual(rows[1]["expires_at"], "2026-01-01 00:00:00.000000")
        # Valid tokens are still registered alongside the failure.
        self.assertEqual(rows[2]["token_hash"], digest(fresh))

    def test_unexpired_token_with_expiry_is_accepted(self):
        self.db.create_schema()
        self.db.add_user("admin", True)
        later = (NOW + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S.%f")
        self.db.add_token(TOKEN, expires_at=later)

        self.assertEqual(self.reconcile(request(TOKEN))[0], 0)

    def test_waits_for_schema_and_admin(self):
        with self.assertRaises(PROVISION.NotReady):
            self.reconcile(request(TOKEN))
        self.db.create_schema()
        with self.assertRaises(PROVISION.NotReady):
            self.reconcile(request(TOKEN))
        self.db.add_user("admin", False)
        with self.assertRaises(PROVISION.NotReady):
            self.reconcile(request(TOKEN, user="missing"))

    def test_refuses_unknown_required_columns(self):
        self.db.create_schema()
        self.db.add_user("admin", True)
        with self.db.engine.begin() as conn:
            conn.exec_driver_sql(
                "ALTER TABLE api_token ADD COLUMN scope VARCHAR(20) NOT NULL DEFAULT 'x'"
            )
        # A NOT NULL column with a server default is fine...
        self.assertEqual(self.reconcile(request(TOKEN))[0], 1)
        # ...one without a default is not.
        with self.db.engine.begin() as conn:
            conn.exec_driver_sql("DROP TABLE api_token")
            conn.exec_driver_sql(
                "CREATE TABLE api_token (id INTEGER NOT NULL PRIMARY KEY, "
                "user_id INTEGER NOT NULL, token_hash VARCHAR(64) NOT NULL, "
                "name VARCHAR(100), created_at DATETIME NOT NULL, "
                "last_used_at DATETIME, expires_at DATETIME, "
                "revoked BOOLEAN NOT NULL, scope VARCHAR(20) NOT NULL)"
            )
        with self.assertRaises(PROVISION.ProvisionError) as caught:
            self.reconcile(request(OTHER_TOKEN))
        self.assertIn("scope", str(caught.exception))

    def test_missing_sqlite_file_is_not_created(self):
        from sqlalchemy.engine import make_url

        missing = self.root / "instance" / "transcriptions.db"
        self.assertTrue(PROVISION._sqlite_file_missing(make_url(f"sqlite:///{missing}")))
        self.assertFalse(missing.exists())
        self.assertFalse(PROVISION._sqlite_file_missing(make_url("postgresql://h/db")))


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd() / "speakr-provision-runner-runtime"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, name, content):
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return str(path)

    def test_parses_env_files_like_podman(self):
        path = self.write(
            "x.env",
            "# comment\n"
            "  EVIDENCE_SPEAKR_API_TOKEN=first\n"
            "BARE_NAME\n"
            "OTHER=a=b\n"
            'QUOTED="kept"\r\n'
            "EVIDENCE_SPEAKR_API_TOKEN=second\n",
        )
        values = RUNNER.parse_env_file(path)
        self.assertEqual(values["EVIDENCE_SPEAKR_API_TOKEN"], "second")
        self.assertEqual(values["OTHER"], "a=b")
        self.assertEqual(values["QUOTED"], '"kept"')
        self.assertNotIn("BARE_NAME", values)

    def test_collects_distinct_tokens_with_file_labels(self):
        api = self.write("evidence-api.env", f"EVIDENCE_SPEAKR_API_TOKEN={TOKEN}\n")
        worker = self.write("evidence-worker.env", f"EVIDENCE_SPEAKR_API_TOKEN={TOKEN}\n")
        self.assertEqual(
            RUNNER.collect_tokens([api, worker]),
            [{"value": TOKEN, "label": "evidence-api.env, evidence-worker.env"}],
        )
        empty = self.write("empty.env", "OTHER=1\n")
        with self.assertRaises(SystemExit):
            RUNNER.collect_tokens([empty])
        with self.assertRaises(SystemExit):
            RUNNER.collect_tokens([str(self.root / "absent.env")])

    def test_end_to_end_through_fake_podman_with_retry(self):
        db = SpeakrDatabase(self.root)
        db.create_schema()
        db.add_user("admin", True)
        db.engine.dispose()
        calls = self.root / "calls"
        fake_podman = self.write(
            "podman",
            f"#!{sys.executable}\n"
            "import os, subprocess, sys\n"
            f"calls = {str(calls)!r}\n"
            "n = int(open(calls).read()) if os.path.exists(calls) else 0\n"
            "open(calls, 'w').write(str(n + 1))\n"
            "assert sys.argv[1:5] == ['exec', '-i', 'speakr', 'python'], sys.argv\n"
            "if n == 0:\n"
            "    print('Error: container is not running', file=sys.stderr)\n"
            "    sys.exit(125)\n"
            "env = dict(os.environ, SQLALCHEMY_DATABASE_URI="
            f"{db.url!r}, ADMIN_USERNAME='admin')\n"
            "sys.exit(subprocess.run([sys.executable] + sys.argv[5:], env=env).returncode)\n",
        )
        os.chmod(fake_podman, 0o755)
        env_file = self.write("evidence-worker.env", f"EVIDENCE_SPEAKR_API_TOKEN={TOKEN}\n")
        config = self.write(
            "config.json",
            json.dumps(
                {
                    "podman": fake_podman,
                    "container": "speakr",
                    "innerScript": os.environ["SPEAKR_PROVISION_SOURCE"],
                    "tokenFiles": [env_file],
                    "user": None,
                    "readyTimeoutSeconds": 30,
                }
            ),
        )

        result = subprocess.run(
            [sys.executable, os.environ["SPEAKR_PROVISION_RUNNER_SOURCE"], config],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(calls.read_text(), "2")
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        self.assertIn("registered it for Speakr user 'admin'", result.stdout)
        self.assertEqual([r["token_hash"] for r in db.tokens()], [digest(TOKEN)])

    def test_gives_up_after_deadline_and_passes_through_hard_failures(self):
        env_file = self.write("w.env", f"EVIDENCE_SPEAKR_API_TOKEN={TOKEN}\n")
        inner = self.write("inner.py", "")
        for code, expected in ((75, 1), (1, 1), (3, 3)):
            fake = self.write(f"podman-{code}", f"#!/bin/sh\nexit {code}\n")
            os.chmod(fake, 0o755)
            clock = iter([0, 5, 10, 400, 800])
            config = {
                "podman": fake,
                "container": "speakr",
                "innerScript": inner,
                "tokenFiles": [env_file],
                "readyTimeoutSeconds": 300,
            }
            with contextlib.redirect_stdout(io.StringIO()):
                rc = RUNNER.run(config, sleep=lambda _: None, monotonic=lambda: next(clock))
            self.assertEqual(rc, expected, code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
