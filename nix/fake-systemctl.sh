#!/usr/bin/env bash
set -euo pipefail

: "${FAKE_SYSTEMCTL_STATE:?}"
: "${FAKE_SYSTEMCTL_LOG:?}"

command="${1:-}"
shift || true

case "$command" in
  is-active)
    unit="${1:?}"
    printf 'IS_ACTIVE %s\n' "$unit" >> "$FAKE_SYSTEMCTL_LOG"
    if grep -Fx "$unit" "$FAKE_SYSTEMCTL_STATE" >/dev/null 2>&1; then
      echo active
      exit 0
    fi
    echo inactive
    exit 3
    ;;
  stop)
    printf 'STOP %s\n' "$*" >> "$FAKE_SYSTEMCTL_LOG"
    if [ "${FAKE_STOP_FAIL:-false}" = true ]; then
      exit 1
    fi
    for unit in "$@"; do
      grep -Fvx "$unit" "$FAKE_SYSTEMCTL_STATE" > "$FAKE_SYSTEMCTL_STATE.next" || true
      mv "$FAKE_SYSTEMCTL_STATE.next" "$FAKE_SYSTEMCTL_STATE"
    done
    if [ -n "${FAKE_FINALIZE_FILE:-}" ]; then
      printf 'quiesced\n' > "$FAKE_FINALIZE_FILE"
    fi
    ;;
  start)
    printf 'START %s\n' "$*" >> "$FAKE_SYSTEMCTL_LOG"
    if [ -n "${FAKE_RESTORE_MARKER:-}" ] && [ -e "$FAKE_RESTORE_MARKER" ]; then
      printf 'REFUSE_RESTORE_MARKER %s\n' "$*" >> "$FAKE_SYSTEMCTL_LOG"
      echo "fake systemctl: restore marker blocks writer startup" >&2
      exit 1
    fi
    if [ "${FAKE_START_FAIL:-false}" = true ]; then
      exit 1
    fi
    if [ -n "${FAKE_EXPECT_FILE:-}" ]; then
      grep -Fx "${FAKE_EXPECT_CONTENT:-restored}" "$FAKE_EXPECT_FILE"
    fi
    for unit in "$@"; do
      if ! grep -Fx "$unit" "$FAKE_SYSTEMCTL_STATE" >/dev/null 2>&1; then
        printf '%s\n' "$unit" >> "$FAKE_SYSTEMCTL_STATE"
      fi
    done
    ;;
  *)
    echo "unsupported fake systemctl command: $command" >&2
    exit 2
    ;;
esac
