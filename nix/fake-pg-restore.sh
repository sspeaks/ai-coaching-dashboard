#!/usr/bin/env bash
set -euo pipefail

: "${FAKE_PG_LOG:?}"

mode=restore
database=""
for arg in "$@"; do
  case "$arg" in
    --list)
      mode=list
      ;;
    --dbname=*)
      database="${arg#--dbname=}"
      ;;
  esac
done

# The dump file is always the final positional argument in both the
# structural-validation (--list) and real restore invocations.
dump_file="${*: -1}"

printf 'PG_RESTORE %s %s\n' "$mode" "$*" >> "$FAKE_PG_LOG"

if [ "$mode" = list ]; then
  if [ "${FAKE_PG_RESTORE_LIST_FAIL:-false}" = true ]; then
    echo "fake pg_restore --list: simulated failure" >&2
    exit 1
  fi
else
  if [ "${FAKE_PG_RESTORE_FAIL:-false}" = true ]; then
    echo "fake pg_restore: simulated restore failure" >&2
    exit 1
  fi
fi

dump_version=$(head -n1 -- "$dump_file" 2>/dev/null || true)
if [ "$dump_version" != FAKE-PG-DUMP-V1 ] && [ "$dump_version" != FAKE-PG-DUMP-V2 ]; then
  echo "fake pg_restore: not a valid fake PostgreSQL dump" >&2
  exit 1
fi

if [ "$mode" = restore ] && [ -n "${FAKE_PG_STATE:-}" ]; then
  : "${database:?fake pg_restore requires --dbname=}"
  database_dir="$FAKE_PG_STATE/databases/$database"
  if [ ! -d "$database_dir" ]; then
    echo "fake pg_restore: target database does not exist: $database" >&2
    exit 1
  fi
  if [ -s "$database_dir/objects" ]; then
    echo "fake pg_restore: target database is not empty: $database" >&2
    exit 1
  fi
  if [ "$dump_version" = FAKE-PG-DUMP-V2 ]; then
    awk 'found { print } /^OBJECTS$/ { found = 1 }' "$dump_file" > "$database_dir/objects"
  else
    tail -n +2 "$dump_file" > "$database_dir/objects"
  fi
fi
