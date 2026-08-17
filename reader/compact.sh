#!/bin/sh
set -eu

READER_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$#" -ne 1 ]; then
  printf 'Usage: %s <task-id>\n' "$0" >&2
  exit 64
fi
TASK_ID=$1
USER_DIR="$READER_DIR/user-data/$TASK_ID"
TASK_DIR="$READER_DIR/../tasks/$TASK_ID"

"$READER_DIR/.venv/bin/python" "$READER_DIR/task_store.py" compact \
  --task-dir "$TASK_DIR"

if [ -d "$USER_DIR/translations" ]; then
  "$READER_DIR/.venv/bin/python" "$READER_DIR/translation_store.py" compact \
    --database "$USER_DIR/translations.sqlite3" \
    --directory "$USER_DIR/translations"
fi

"$READER_DIR/.venv/bin/python" "$READER_DIR/runtime_store.py" compact \
  --database "$USER_DIR/state.sqlite3" \
  --user-dir "$USER_DIR"

"$READER_DIR/.venv/bin/python" "$READER_DIR/build_site.py" \
  --task-id "$TASK_ID" \
  --database "$USER_DIR/site.sqlite3"

printf 'Consolidated Reader runtime data into SQLite.\n'
