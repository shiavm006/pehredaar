#!/usr/bin/env bash
# End-to-end video harness wrapper.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  exec "$ROOT/.venv/bin/python" "$ROOT/scripts/run_video_tests.py" "$@"
fi
exec python3 "$ROOT/scripts/run_video_tests.py" "$@"
