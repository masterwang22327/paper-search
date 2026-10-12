#!/bin/sh
# Sourced by build.sh and serve.sh so a new machine uses a supported Python.
set -eu

if [ ! -x "$READER_DIR/.venv/bin/python" ]; then
  READER_PYTHON=${PYTHON_BIN:-}
  if [ -z "$READER_PYTHON" ]; then
    for candidate in python3.13 python3.12 python3.11 python3; do
      if command -v "$candidate" >/dev/null 2>&1 && \
          "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
        READER_PYTHON=$candidate
        break
      fi
    done
  fi
  if [ -z "$READER_PYTHON" ] || ! "$READER_PYTHON" -c \
      'import sys; sys.exit(sys.version_info < (3, 11))'; then
    printf 'Python 3.11+ is required. Set PYTHON_BIN to its executable.\n' >&2
    exit 1
  fi
  "$READER_PYTHON" -m venv "$READER_DIR/.venv"
fi

if ! "$READER_DIR/.venv/bin/python" -c 'import tomllib' >/dev/null 2>&1; then
  printf 'reader/.venv uses an old Python; recreate it with Python 3.11+.\n' >&2
  exit 1
fi

if [ ! -x "$READER_DIR/.venv/bin/mkdocs" ]; then
  if [ -z "${PIP_CERT:-}" ] && [ -f /etc/ssl/cert.pem ]; then
    PIP_CERT=/etc/ssl/cert.pem
    export PIP_CERT
  fi
  "$READER_DIR/.venv/bin/python" -m pip install -r "$READER_DIR/requirements-lock.txt"
fi
