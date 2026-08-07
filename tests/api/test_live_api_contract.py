"""Live HTTP contract coverage for the locally launched evidence API."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_PARENT = ROOT / ".test-runtime"
PROXY_SECRET = "synthetic-live-contract-proxy-secret"
PROXY_SECRET_HEADER = "X-AI-Coaching-Proxy-Auth"
EMAIL_HEADER = "X-Auth-Request-Email"
GROUPS_HEADER = "X-Auth-Request-Groups"
VIEWER_HEADERS = {
    EMAIL_HEADER: "viewer@example.invalid",
    PROXY_SECRET_HEADER: PROXY_SECRET,
}
EDITOR_HEADERS = {
    EMAIL_HEADER: "editor@example.invalid",
    GROUPS_HEADER: "contract-editors",
    PROXY_SECRET_HEADER: PROXY_SECRET,
}
ADMIN_HEADERS = {
    EMAIL_HEADER: "admin@example.invalid",
    GROUPS_HEADER: "contract-admins",
    PROXY_SECRET_HEADER: PROXY_SECRET,
}


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class LiveApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        RUNTIME_PARENT.mkdir(exist_ok=True)
        cls.runtime = RUNTIME_PARENT / f"live-api-{uuid4()}"
        cls.runtime.mkdir()
        cls.database = cls.runtime / "evidence.db"
        cls.media_root = cls.runtime / "media"
        cls.log_path = cls.runtime / "api.log"
        cls.port = available_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.env = {
            **os.environ,
            "EVIDENCE_ENVIRONMENT": "test",
            "EVIDENCE_AUTH_MODE": "trusted_proxy",
            "EVIDENCE_TRUSTED_EMAIL_HEADER": EMAIL_HEADER,
            "EVIDENCE_TRUSTED_GROUPS_HEADER": GROUPS_HEADER,
            "EVIDENCE_TRUSTED_PROXY_NETWORKS": "127.0.0.1/32",
            "EVIDENCE_EDITOR_GROUPS": "contract-editors",
            "EVIDENCE_ADMIN_GROUPS": "contract-admins",
            "EVIDENCE_TRUSTED_PROXY_SECRET_HEADER": PROXY_SECRET_HEADER,
            "EVIDENCE_TRUSTED_PROXY_SHARED_SECRET": PROXY_SECRET,
            "EVIDENCE_SPEAKR_WEBHOOK_SECRET": "synthetic-webhook-secret",
            "EVIDENCE_SPEAKR_TIMEOUT_SECONDS": "1",
            "EVIDENCE_EXTRACTION_TIMEOUT_SECONDS": "1",
            "EVIDENCE_WORKER_TRANSCRIPTION_POLL_SECONDS": "0",
            "EVIDENCE_WORKER_MAX_ATTEMPTS": "1",
            "EVIDENCE_DATABASE_URL": f"sqlite:///{cls.database}",
            "EVIDENCE_MEDIA_ROOT": str(cls.media_root),
            "PYTHONUNBUFFERED": "1",
        }
        cls.log = cls.log_path.open("w+", encoding="utf-8")
        cls.server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "evidence_api.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(cls.port),
                "--log-level",
                "info",
            ],
            cwd=ROOT,
            env=cls.env,
            stdout=cls.log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if cls.server.poll() is not None:
                raise RuntimeError(f"API exited during startup:\n{cls.server_output()}")
            try:
                status, payload = cls.request("GET", "/api/health")
                if status == 200 and payload["status"] == "ok":
                    return
            except (OSError, ValueError):
                time.sleep(0.1)
        cls.stop_server()
        raise RuntimeError(
            f"API did not become healthy within 20 seconds:\n{cls.server_output()}"
        )

    @classmethod
    def tearDownClass(cls):
        cls.stop_server()
        if getattr(cls, "log", None):
            cls.log.close()
        shutil.rmtree(cls.runtime, ignore_errors=True)
        try:
            RUNTIME_PARENT.rmdir()
        except OSError:
            pass

    @classmethod
    def server_output(cls) -> str:
        cls.log.flush()
        return cls.log_path.read_text(encoding="utf-8", errors="replace")

    @classmethod
    def stop_server(cls):
        server = getattr(cls, "server", None)
        if not server or server.poll() is not None:
            return
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)

    @classmethod
    def request(
        cls,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, object]:
        request = urllib.request.Request(
            cls.base_url + path,
            data=body,
            method=method,
            headers={"Accept": "application/json", **(headers or {})},
        )
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            try:
                payload = json.loads(raw) if raw else None
            except json.JSONDecodeError as error:
                raise AssertionError(
                    f"{method} {path} returned non-JSON HTTP {response.status}: "
                    f"{raw.decode(errors='replace')}\nAPI log:\n{cls.server_output()}"
                ) from error
            return response.status, payload

    @classmethod
    def json_request(
        cls,
        method: str,
        path: str,
        document: object,
        *,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, object]:
        return cls.request(
            method,
            path,
            body=json.dumps(document).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
        )

    @classmethod
    def create_session(cls, headers: dict[str, str], title: str) -> dict:
        status, session = cls.json_request(
            "POST",
            "/api/sessions",
            {"title": title, "duration_ms": 3_000},
            headers=headers,
        )
        if status != 201:
            raise AssertionError(
                f"session creation returned HTTP {status}: {session}\n"
                f"API log:\n{cls.server_output()}"
            )
        return session

    def test_health_and_trusted_proxy_rbac(self):
        status, health = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["database"], "ok")
        self.assertFalse(health["speakr_configured"])
        self.assertEqual(health["extraction_provider"], "disabled")

        status, unauthorized = self.json_request(
            "POST",
            "/api/sessions",
            {"title": "missing identity"},
            headers={PROXY_SECRET_HEADER: PROXY_SECRET},
        )
        self.assertEqual(status, 401)
        self.assertEqual(unauthorized["detail"]["code"], "authentication_required")

        status, rejected_identity = self.request(
            "GET",
            "/api/sessions",
            headers={EMAIL_HEADER: "viewer@example.invalid"},
        )
        self.assertEqual(
            status,
            401,
            "trusted identity headers must be rejected without the configured "
            "proxy shared-secret header",
        )
        self.assertEqual(
            rejected_identity["detail"]["code"], "proxy_secret_required"
        )

        status, sessions = self.request(
            "GET", "/api/sessions", headers=VIEWER_HEADERS
        )
        self.assertEqual(status, 200)
        self.assertIsInstance(sessions, list)
        status, forbidden = self.json_request(
            "POST",
            "/api/sessions",
            {"title": "viewer cannot mutate"},
            headers=VIEWER_HEADERS,
        )
        self.assertEqual(status, 403)
        self.assertEqual(forbidden["detail"]["code"], "insufficient_role")

        session = self.create_session(EDITOR_HEADERS, "Editor-created session")
        status, forbidden = self.request(
            "DELETE", f"/api/sessions/{session['id']}", headers=EDITOR_HEADERS
        )
        self.assertEqual(status, 403)
        self.assertEqual(forbidden["detail"]["code"], "insufficient_role")

    def test_upload_status_provider_failure_and_cancel_contract(self):
        session = self.create_session(
            EDITOR_HEADERS, "Synthetic provider-failure contract"
        )
        session_id = session["id"]
        media = b"synthetic-contract-audio-not-a-recording"
        boundary = "copilot-contract-boundary"
        multipart = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="media"; filename="fixture.bin"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + media + f"\r\n--{boundary}--\r\n".encode()
        status, uploaded = self.request(
            "POST",
            f"/api/sessions/{session_id}/media",
            body=multipart,
            headers={
                **EDITOR_HEADERS,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(uploaded["state"], "TRANSCRIBING")
        self.assertEqual(uploaded["media_sha256"], hashlib.sha256(media).hexdigest())
        stored_files = list((self.media_root / session_id).iterdir())
        self.assertEqual(len(stored_files), 1)
        self.assertEqual(stored_files[0].read_bytes(), media)

        status, jobs = self.request(
            "GET", f"/api/sessions/{session_id}/jobs", headers=VIEWER_HEADERS
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(jobs), 1)
        self.assertEqual((jobs[0]["type"], jobs[0]["status"]), ("TRANSCRIBE", "QUEUED"))

        worker = subprocess.run(
            [sys.executable, "-m", "evidence_worker", "--once"],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(
            worker.returncode,
            0,
            f"worker failed:\nstdout:\n{worker.stdout}\nstderr:\n{worker.stderr}",
        )
        status, jobs = self.request(
            "GET", f"/api/sessions/{session_id}/jobs", headers=VIEWER_HEADERS
        )
        self.assertEqual(status, 200)
        self.assertEqual(jobs[0]["status"], "FAILED")
        self.assertEqual(jobs[0]["error_code"], "adapter_not_configured")
        self.assertIn("EVIDENCE_SPEAKR_BASE_URL", jobs[0]["error_message"])
        status, failed_session = self.request(
            "GET", f"/api/sessions/{session_id}", headers=VIEWER_HEADERS
        )
        self.assertEqual(status, 200)
        self.assertEqual(failed_session["state"], "FAILED")
        self.assertIn("adapter_not_configured", failed_session["last_error"])

        cancellable = self.create_session(EDITOR_HEADERS, "Deterministic cancellation")
        status, forbidden = self.request(
            "POST",
            f"/api/sessions/{cancellable['id']}/cancel",
            headers=VIEWER_HEADERS,
        )
        self.assertEqual(status, 403)
        self.assertEqual(forbidden["detail"]["code"], "insufficient_role")
        status, cancelled = self.request(
            "POST",
            f"/api/sessions/{cancellable['id']}/cancel",
            headers=EDITOR_HEADERS,
        )
        self.assertEqual(status, 200)
        self.assertEqual(cancelled["state"], "CANCELLED")

    def test_ledger_verification_and_confirmed_deletion(self):
        session = self.create_session(EDITOR_HEADERS, "Synthetic ledger contract")
        session_id = session["id"]
        revision_id = str(uuid4())
        segments = [
            {
                "segment_id": "segment-1",
                "start_ms": 1_000,
                "end_ms": 2_000,
                "text": "Release the sound instead of pushing.",
                "provider_speaker_label": "SPEAKER_00",
            }
        ]
        with sqlite3.connect(self.database) as database:
            database.execute(
                """
                INSERT INTO transcript_revision
                    (id, session_id, sha256, segments, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    session_id,
                    hashlib.sha256(json.dumps(segments).encode()).hexdigest(),
                    json.dumps(segments),
                    "synthetic-contract",
                    datetime.now(UTC).isoformat(),
                ),
            )
            database.execute(
                """
                UPDATE coaching_session
                SET current_transcript_revision_id = ?, state = ?
                WHERE id = ?
                """,
                (revision_id, "TRANSCRIPT_READY", session_id),
            )
            database.commit()

        status, entry = self.json_request(
            "POST",
            f"/api/sessions/{session_id}/ledger",
            {
                "topic": "Release",
                "exact_coach_feedback": "Release the sound instead of pushing.",
                "confidence": 0.8,
                "evidence": [
                    {
                        "transcript_revision_id": revision_id,
                        "start_ms": 1_000,
                        "end_ms": 2_000,
                        "segment_ids": ["segment-1"],
                    }
                ],
            },
            headers=EDITOR_HEADERS,
        )
        self.assertEqual(status, 201)
        self.assertEqual(entry["verification_status"], "UNVERIFIED")

        status, forbidden = self.json_request(
            "PUT",
            f"/api/ledger/{entry['id']}/verification",
            {"status": "VERIFIED"},
            headers=VIEWER_HEADERS,
        )
        self.assertEqual(status, 403)
        self.assertEqual(forbidden["detail"]["code"], "insufficient_role")
        status, verified = self.json_request(
            "PUT",
            f"/api/ledger/{entry['id']}/verification",
            {"status": "VERIFIED", "note": "Checked against synthetic evidence."},
            headers=EDITOR_HEADERS,
        )
        self.assertEqual(status, 200)
        self.assertEqual(verified["verified_by"], "editor@example.invalid")
        status, ledger = self.request(
            "GET", f"/api/sessions/{session_id}/ledger", headers=VIEWER_HEADERS
        )
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in ledger], [entry["id"]])

        deletable = self.create_session(EDITOR_HEADERS, "Confirmed deletion")
        deletable_id = deletable["id"]
        status, pending = self.request(
            "DELETE", f"/api/sessions/{deletable_id}", headers=ADMIN_HEADERS
        )
        self.assertEqual(status, 200)
        self.assertEqual(pending["state"], "DELETE_PENDING")
        status, mismatch = self.json_request(
            "POST",
            f"/api/sessions/{deletable_id}/deletion/confirm",
            {"confirm_session_id": "wrong"},
            headers=ADMIN_HEADERS,
        )
        self.assertEqual(status, 400)
        self.assertEqual(
            mismatch["detail"]["code"], "deletion_confirmation_mismatch"
        )
        status, payload = self.json_request(
            "POST",
            f"/api/sessions/{deletable_id}/deletion/confirm",
            {"confirm_session_id": deletable_id},
            headers=ADMIN_HEADERS,
        )
        self.assertEqual((status, payload), (204, None))
        status, missing = self.request(
            "GET", f"/api/sessions/{deletable_id}", headers=VIEWER_HEADERS
        )
        self.assertEqual(status, 404)
        self.assertEqual(missing["detail"]["code"], "session_not_found")


if __name__ == "__main__":
    unittest.main()
