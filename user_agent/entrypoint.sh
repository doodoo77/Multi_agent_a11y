#!/usr/bin/env sh
set -eu

: "${TARGET_URL:?TARGET_URL is required (set in .env)}"
OUT_DIR="${OUT_DIR:-/shared/out}"
STEPS="${STEPS:-50}"
MAX_EVIDENCE="${MAX_EVIDENCE:-30}"

# ? expert_agent ready 신호 대기
READY_FILE="${READY_FILE:-/shared/expert_ready}"
until [ -f "$READY_FILE" ]; do
  echo "[user_agent] waiting for expert_agent... ($READY_FILE)"
  sleep 2
done

python -m user_agent.cli "$TARGET_URL" "$OUT_DIR" "$STEPS" "$MAX_EVIDENCE"