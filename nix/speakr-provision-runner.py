"""Host side of ai-coaching-speakr-provision.service.

Reads EVIDENCE_SPEAKR_API_TOKEN from the evidence API/worker env files (the
same files their containers load), then runs nix/speakr-provision.py inside
the Speakr container with the token(s) on stdin, retrying while Speakr is
still starting. Usage: speakr-provision-runner.py <config.json>
"""

import json
import os
import subprocess
import sys
import time

EX_TEMPFAIL = 75
# `podman exec` exit status when the container exists but is not running yet.
PODMAN_CONTAINER_NOT_RUNNING = 125
TOKEN_KEY = "EVIDENCE_SPEAKR_API_TOKEN"


def log(message):
    print(f"[speakr-provision] {message}", flush=True)


def parse_env_file(path):
    """Parse a file the way `podman --env-file` does: leading whitespace is
    ignored, `#` lines and lines without `=` are skipped, the value is taken
    verbatim after the first `=` (no quote stripping), and the last
    assignment of a key wins."""
    values = {}
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\r\n").lstrip(" \t")
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key] = value
    return values


def collect_tokens(paths):
    """Return [{"value", "label"}] for each distinct token, labelled with the
    env files that carry it (file names only; never the value)."""
    sources = {}
    for path in paths:
        try:
            value = parse_env_file(path).get(TOKEN_KEY)
        except FileNotFoundError:
            raise SystemExit(f"[speakr-provision] ERROR: env file {path} does not exist")
        if not value:
            log(f"warning: {path} does not set {TOKEN_KEY}")
            continue
        sources.setdefault(value, []).append(os.path.basename(path))
    if not sources:
        raise SystemExit(
            f"[speakr-provision] ERROR: none of {', '.join(paths)} sets {TOKEN_KEY}"
        )
    if len(sources) > 1:
        log(f"warning: the env files carry {len(sources)} different {TOKEN_KEY} values")
    return [
        {"value": value, "label": ", ".join(files)} for value, files in sources.items()
    ]


def run(config, sleep=time.sleep, monotonic=time.monotonic):
    with open(config["innerScript"], encoding="utf-8") as handle:
        inner_source = handle.read()
    request = json.dumps(
        {"tokens": collect_tokens(config["tokenFiles"]), "user": config.get("user")}
    )
    command = [
        config["podman"],
        "exec",
        "-i",
        config["container"],
        "python",
        "-c",
        inner_source,
    ]
    deadline = monotonic() + config["readyTimeoutSeconds"]
    while True:
        result = subprocess.run(command, input=request, text=True, check=False)
        if result.returncode == 0:
            return 0
        if result.returncode not in (EX_TEMPFAIL, PODMAN_CONTAINER_NOT_RUNNING):
            return result.returncode
        if monotonic() >= deadline:
            log(
                f"ERROR: Speakr was not ready within {config['readyTimeoutSeconds']}s"
            )
            return 1
        sleep(3)


def main(argv):
    if len(argv) != 2:
        print(f"usage: {argv[0]} <config.json>", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as handle:
        config = json.load(handle)
    return run(config)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
