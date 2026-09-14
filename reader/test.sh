#!/bin/sh
set -eu

READER_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ ! -x "$READER_DIR/.venv/bin/playwright" ]; then
  PIP_CERT=${PIP_CERT:-/etc/ssl/cert.pem} \
    "$READER_DIR/.venv/bin/python" -m pip install -r "$READER_DIR/requirements-dev.txt"
fi

cd "$READER_DIR"
"$READER_DIR/build.sh" paper-research-base-knowledge-about-llm-20260717
"$READER_DIR/.venv/bin/python" "$READER_DIR/tests/test_storage.py"
"$READER_DIR/.venv/bin/python" "$READER_DIR/tests/test_prepare_docs.py"
"$READER_DIR/.venv/bin/python" "$READER_DIR/tests/test_knowledge_api.py"
"$READER_DIR/.venv/bin/python" "$READER_DIR/tests/test_page_insight.py"
"$READER_DIR/.venv/bin/python" "$READER_DIR/tests/test_revision_layout.py"
"$READER_DIR/.venv/bin/python" "$READER_DIR/tests/test_selection_contexts.py"
"$READER_DIR/.venv/bin/python" "$READER_DIR/tests/test_revision_context.py"
"$READER_DIR/.venv/bin/python" "$READER_DIR/tests/test_knowledge_math.py"
exec "$READER_DIR/.venv/bin/python" "$READER_DIR/tests/test_reader.py"
