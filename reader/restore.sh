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

if [ -f "$TASK_DIR/artifacts.sqlite3" ]; then
  "$READER_DIR/.venv/bin/python" "$READER_DIR/task_store.py" restore \
    --task-dir "$TASK_DIR"
fi

if [ -f "$USER_DIR/state.sqlite3" ]; then
  "$READER_DIR/.venv/bin/python" "$READER_DIR/runtime_store.py" restore \
    --database "$USER_DIR/state.sqlite3" \
    --user-dir "$USER_DIR"
fi

if [ -f "$USER_DIR/translations.sqlite3" ] && [ ! -e "$USER_DIR/translations" ]; then
  "$READER_DIR/.venv/bin/python" "$READER_DIR/translation_store.py" restore \
    --database "$USER_DIR/translations.sqlite3" \
    --directory "$USER_DIR/translations"
fi

printf 'Restored source artifacts plus legacy runtime and translation files. The site remains SQLite-native.\n'
