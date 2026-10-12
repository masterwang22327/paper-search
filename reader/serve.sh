#!/bin/sh
set -eu

READER_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$#" -ne 1 ]; then
  printf 'Usage: %s <task-id>\n' "$0" >&2
  exit 64
fi
TASK_ID=$1
USER_DIR="$READER_DIR/user-data/$TASK_ID"

. "$READER_DIR/setup.sh"

if [ -z "${CODEX_HOME:-}" ] && [ -f "$READER_DIR/../.reader-codex/config.toml" ]; then
  CODEX_HOME=$(CDPATH= cd -- "$READER_DIR/../.reader-codex" && pwd)
  export CODEX_HOME
fi

if [ -d "$USER_DIR/translations" ]; then
  "$READER_DIR/.venv/bin/python" "$READER_DIR/translation_store.py" compact \
    --database "$USER_DIR/translations.sqlite3" \
    --directory "$USER_DIR/translations"
fi

"$READER_DIR/.venv/bin/python" "$READER_DIR/runtime_store.py" compact \
  --database "$USER_DIR/state.sqlite3" \
  --user-dir "$USER_DIR"

if "$READER_DIR/.venv/bin/python" "$READER_DIR/build_site.py" \
  --task-id "$TASK_ID" \
  --database "$USER_DIR/site.sqlite3" \
  --check >/dev/null 2>&1; then
  printf 'Reusing current Reader site database: %s\n' "$USER_DIR/site.sqlite3"
else
  "$READER_DIR/.venv/bin/python" "$READER_DIR/build_site.py" \
    --task-id "$TASK_ID" \
    --database "$USER_DIR/site.sqlite3"
fi

"$READER_DIR/.venv/bin/python" "$READER_DIR/server.py" --task-id "$TASK_ID" --port "${READER_PORT:-8000}"
