import http.client
import http.server
import json
import os
import queue
import socket
import subprocess
import threading
import time
from pathlib import Path


AUTH_PORT = int(os.environ["AUTH_PORT"])
BACKEND_PORT = int(os.environ["BACKEND_PORT"])
CADDY_PORT = int(os.environ["CADDY_PORT"])
EXPECTED_SECRET = os.environ["AI_COACHING_PROXY_AUTH_SECRET"]


class Server(http.server.ThreadingHTTPServer):
    allow_reuse_address = True


class AuthHandler(http.server.BaseHTTPRequestHandler):
    calls = 0

    def do_GET(self):
        type(self).calls += 1
        self.send_response(202)
        self.send_header("X-Auth-Request-User", "oidc-subject")
        self.send_header("X-Auth-Request-Email", "real@example.invalid")
        self.send_header("X-Auth-Request-Groups", "evidence-editors")
        self.send_header("X-Auth-Request-Preferred-Username", "real")
        self.end_headers()

    def log_message(self, *_args):
        pass


class BackendHandler(http.server.BaseHTTPRequestHandler):
    requests = queue.Queue()

    def _capture(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        type(self).requests.put(
            {
                "method": self.command,
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
            }
        )
        body = json.dumps({"path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _capture
    do_POST = _capture

    def log_message(self, *_args):
        pass


def start_server(port, handler):
    server = Server(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def wait_for_caddy(process):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(Path("caddy.log").read_text(encoding="utf-8"))
        try:
            with socket.create_connection(("127.0.0.1", CADDY_PORT), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("Caddy did not start")


def request(method, path, headers, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", CADDY_PORT, timeout=5)
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    response_body = response.read()
    connection.close()
    if response.status != 200:
        raise AssertionError((response.status, response_body))


def assert_api_request(captured):
    assert captured["path"] == "/api/health?probe=1", captured
    headers = captured["headers"]
    assert headers["x-auth-request-email"] == "real@example.invalid", headers
    assert headers["x-auth-request-groups"] == "evidence-editors", headers
    assert headers["x-ai-coaching-proxy-auth"] == EXPECTED_SECRET, headers
    assert headers.get("x-remote-user") is None, headers
    assert "203.0.113.99" not in headers.get("x-forwarded-for", ""), headers


def assert_webhook_request(captured):
    assert captured["path"] == "/api/webhooks/speakr", captured
    headers = captured["headers"]
    assert headers["x-ai-coaching-proxy-auth"] == EXPECTED_SECRET, headers
    assert headers.get("x-auth-request-email") is None, headers
    assert headers.get("x-auth-request-groups") is None, headers
    assert headers.get("x-remote-user") is None, headers


def main():
    auth_server = start_server(AUTH_PORT, AuthHandler)
    backend_server = start_server(BACKEND_PORT, BackendHandler)
    log = Path("caddy.log").open("w", encoding="utf-8")
    environment = os.environ.copy()
    environment["XDG_DATA_HOME"] = str(Path.cwd() / "caddy-data")
    environment["XDG_CONFIG_HOME"] = str(Path.cwd() / "caddy-config")
    caddy = subprocess.Popen(
        [os.environ["CADDY_BIN"], "run", "--config", "Caddyfile", "--adapter", "caddyfile"],
        env=environment,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_for_caddy(caddy)
        forged_headers = {
            "X-Auth-Request-Email": "forged@example.invalid",
            "X-Auth-Request-Groups": "evidence-admins",
            "X-Forwarded-For": "203.0.113.99",
            "X-Remote-User": "forged",
            "X-AI-Coaching-Proxy-Auth": "forged-hop-secret",
        }
        request("GET", "/api/health?probe=1", forged_headers)
        assert_api_request(BackendHandler.requests.get(timeout=2))
        assert AuthHandler.calls == 1

        request(
            "POST",
            "/api/webhooks/speakr",
            forged_headers | {"Content-Type": "application/json"},
            body=b"{}",
        )
        assert_webhook_request(BackendHandler.requests.get(timeout=2))
        assert AuthHandler.calls == 1, "webhook unexpectedly used browser OIDC"
    finally:
        caddy.terminate()
        try:
            caddy.wait(timeout=5)
        except subprocess.TimeoutExpired:
            caddy.kill()
            caddy.wait(timeout=5)
        log.close()
        auth_server.shutdown()
        backend_server.shutdown()


if __name__ == "__main__":
    main()
