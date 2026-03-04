#!/usr/bin/env sh
set -eu

CHROMA_DIR="${CHROMA_DIR:-/app/chroma}"
DOCS_DIR="${DOCS_DIR:-/app/docs}"
READY_FILE="${READY_FILE:-/shared/expert_ready}"   # ? Ãß°¡

# Ingest once on cold start (empty persist dir or missing marker)
if [ ! -f "$CHROMA_DIR/.ingested" ]; then
  echo "[expert_agent] ingest: starting (marker not found)"
  mkdir -p "$CHROMA_DIR"
  python ingest.py || true
  touch "$CHROMA_DIR/.ingested"
  echo "[expert_agent] ingest: done"
else
  echo "[expert_agent] ingest: skipped (marker exists)"
fi

mkdir -p "$(dirname "$READY_FILE")" || true
echo "[expert_agent] about to touch ready file: $READY_FILE"
touch "$READY_FILE"
echo "[expert_agent] touched ready file OK"
echo "[expert_agent] ready: $(ls -l "$READY_FILE" 2>/dev/null || echo "$READY_FILE")"

exec python consumer.py