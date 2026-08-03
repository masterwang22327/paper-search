#!/bin/sh
set -eu

READER_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$#" -ne 1 ]; then
  printf 'Usage: %s <task-id>\n' "$0" >&2
  exit 64
fi
TASK_ID=$1

if [ ! -x "$READER_DIR/.venv/bin/mkdocs" ]; then
  python3 -m venv "$READER_DIR/.venv"
  PIP_CERT=${PIP_CERT:-/etc/ssl/cert.pem} \
    "$READER_DIR/.venv/bin/python" -m pip install -r "$READER_DIR/requirements.txt"
fi

"$READER_DIR/.venv/bin/python" "$READER_DIR/scripts/prepare_docs.py" --task-id "$TASK_ID"
cd "$READER_DIR"
"$READER_DIR/.venv/bin/mkdocs" build --clean --strict
exec "$READER_DIR/.venv/bin/python" "$READER_DIR/server.py" --task-id "$TASK_ID" --port 8000
