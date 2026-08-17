#!/bin/sh
set -eu

READER_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$#" -ne 1 ]; then
  printf 'Usage: %s <task-id>\n' "$0" >&2
  exit 64
fi
TASK_ID=$1
USER_DIR="$READER_DIR/user-data/$TASK_ID"

if [ ! -x "$READER_DIR/.venv/bin/mkdocs" ]; then
  python3 -m venv "$READER_DIR/.venv"
  PIP_CERT=${PIP_CERT:-/etc/ssl/cert.pem} \
    "$READER_DIR/.venv/bin/python" -m pip install -r "$READER_DIR/requirements.txt"
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

"$READER_DIR/.venv/bin/python" "$READER_DIR/server.py" --task-id "$TASK_ID" --port 8000
