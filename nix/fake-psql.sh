#!/usr/bin/env bash
set -euo pipefail

: "${FAKE_PG_LOG:?}"
: "${FAKE_PG_STATE:?}"

declare -A variables=()
username=""
database=""
command_text=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --username=*)
      username="${1#--username=}"
      ;;
    --dbname=*)
      database="${1#--dbname=}"
      ;;
    --set=*)
      assignment="${1#--set=}"
      variables["${assignment%%=*}"]="${assignment#*=}"
      ;;
    --command=*)
      command_text="${1#--command=}"
      ;;
    --command)
      shift
      command_text="${1:?}"
      ;;
  esac
  shift
done

if [ -z "$command_text" ]; then
  command_text=$(cat)
fi
printf 'PSQL user=%s db=%s %s\n' "$username" "$database" \
  "$(printf '%s' "$command_text" | tr '\n' ' ')" >> "$FAKE_PG_LOG"

if [ "$username" = evidence ] && [ -n "${FAKE_PG_PASSWORD:-}" ] \
  && [ "${PGPASSWORD:-}" != "$FAKE_PG_PASSWORD" ]; then
  echo "fake psql: invalid password" >&2
  exit 1
fi

databases="$FAKE_PG_STATE/databases"
mkdir -p "$databases"

if [[ "$command_text" == *AI_COACHING_PREPARE_REPLACEMENT* ]]; then
  target="${variables[target_db]:?}"
  replacement="${variables[replacement_db]:?}"
  displaced="${variables[displaced_db]:?}"
  rm -rf -- "$databases/${replacement:?}" "$databases/${displaced:?}"
  mkdir -p "$databases/$replacement"
  : > "$databases/$replacement/objects"
  cp "$databases/$target/owner" "$databases/$replacement/owner"
  : > "$databases/$replacement/acl"
  exit 0
fi

if [[ "$command_text" == *AI_COACHING_APPLY_DATABASE_METADATA* ]]; then
  if [ "${FAKE_PG_METADATA_FAIL:-false}" = true ]; then
    echo "fake psql: simulated metadata SQL failure" >&2
    exit 1
  fi
  target="${variables[target_db]:?}"
  replacement="${variables[replacement_db]:?}"
  cp "$databases/$target/owner" "$databases/$replacement/owner"
  cp "$databases/$target/acl" "$databases/$replacement/acl"
  if [ -f "$databases/$target/settings" ]; then
    cp "$databases/$target/settings" "$databases/$replacement/settings"
  else
    rm -f -- "$databases/$replacement/settings"
  fi
  exit 0
fi

if [[ "$command_text" == *AI_COACHING_SWAP_DATABASES* ]]; then
  target="${variables[target_db]:?}"
  replacement="${variables[replacement_db]:?}"
  displaced="${variables[displaced_db]:?}"
  test -d "$databases/$target"
  test -d "$databases/$replacement"
  test ! -e "$databases/$displaced"
  mv -- "$databases/$target" "$databases/$displaced"
  mv -- "$databases/$replacement" "$databases/$target"
  exit 0
fi

if [[ "$command_text" == *AI_COACHING_DROP_DISPLACED* ]]; then
  rm -rf -- "$databases/${variables[displaced_db]:?}"
  exit 0
fi

if [[ "$command_text" == *pg_get_userbyid* ]]; then
  cat "$databases/${variables[target_db]:?}/owner"
  exit 0
fi

if [[ "$command_text" == *datconnlimit* ]]; then
  printf '%s\n' -1
  exit 0
fi

if [[ "$command_text" == *"SELECT 1"* ]]; then
  test -d "$databases/${variables[target_db]:-$database}"
  printf '%s\n' 1
  exit 0
fi

echo "fake psql: unsupported command" >&2
exit 2
