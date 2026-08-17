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

SITE_DATABASE="$READER_DIR/user-data/$TASK_ID/site.sqlite3"
"$READER_DIR/.venv/bin/python" "$READER_DIR/build_site.py" \
  --task-id "$TASK_ID" \
  --database "$SITE_DATABASE"
printf 'Built SQLite Reader site at %s\n' "$SITE_DATABASE"
