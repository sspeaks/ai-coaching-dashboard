#!/usr/bin/env bash
set -euo pipefail

: "${FAKE_PG_LOG:?}"

file=""
database=""
for arg in "$@"; do
  case "$arg" in
    --file=*)
      file="${arg#--file=}"
      ;;
    -*)
      ;;
    *)
      database="$arg"
      ;;
  esac
done

printf 'PG_DUMP %s\n' "$*" >> "$FAKE_PG_LOG"

if [ "${FAKE_PG_DUMP_FAIL:-false}" = true ]; then
  echo "fake pg_dump: simulated failure" >&2
  exit 1
fi

: "${file:?fake pg_dump requires --file=}"
if [ -n "${FAKE_PG_STATE:-}" ]; then
  : "${database:?fake pg_dump requires a database name}"
  database_dir="$FAKE_PG_STATE/databases/$database"
  if [ ! -d "$database_dir" ]; then
    echo "fake pg_dump: database does not exist: $database" >&2
    exit 1
  fi
  {
    printf 'FAKE-PG-DUMP-V2\n'
    printf 'OWNER %s\n' "$(cat "$database_dir/owner")"
    printf 'ACL %s\n' "$(cat "$database_dir/acl")"
    printf 'OBJECTS\n'
    cat "$database_dir/objects"
  } > "$file"
else
  printf 'FAKE-PG-DUMP-V1\n%s\n' "${FAKE_PG_DUMP_CONTENT:-dump-data}" > "$file"
fi
