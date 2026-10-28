#!/usr/bin/env bash
# Publish the captured frigate/reviews fixture to Mosquitto (no camera needed).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FIXTURE="${1:-$ROOT/tests/fixtures/review_new.json}"

if [[ ! -f "$FIXTURE" ]]; then
  echo "Fixture not found: $FIXTURE" >&2
  exit 1
fi

if ! command -v mosquitto_pub >/dev/null 2>&1; then
  echo "Missing mosquitto_pub. Install with: brew install mosquitto" >&2
  exit 1
fi

echo "Publishing $(basename "$FIXTURE") → frigate/reviews"
mosquitto_pub -h localhost -t frigate/reviews -f "$FIXTURE"
echo "Done."
