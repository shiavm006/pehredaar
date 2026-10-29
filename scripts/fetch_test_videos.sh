#!/usr/bin/env bash
# Download the harness clips listed in test_videos/SOURCES.tsv.
# The mp4s are gitignored (size), so a fresh clone needs this before
# ./scripts/run_video_tests.sh will do anything.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TSV="$ROOT/test_videos/SOURCES.tsv"
DEST="$ROOT/test_videos"

[[ -f "$TSV" ]] || { echo "Missing $TSV" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "Missing 'curl'" >&2; exit 1; }

got=0 skipped=0 failed=0
# Skip the header row; columns are: file, title, page, cdn
while IFS=$'\t' read -r file title page cdn; do
  [[ -z "${file:-}" || -z "${cdn:-}" ]] && continue
  out="$DEST/$file"
  if [[ -s "$out" ]]; then
    echo "  = $file (already present)"
    skipped=$((skipped + 1))
    continue
  fi
  echo "  > $file  <- $cdn"
  # -f so a 404 is an error rather than a saved HTML page.
  if curl -fsSL --retry 2 -o "$out.part" "$cdn"; then
    mv "$out.part" "$out"
    got=$((got + 1))
  else
    rm -f "$out.part"
    echo "    FAILED: $file — fetch manually from $page" >&2
    failed=$((failed + 1))
  fi
done < <(tail -n +2 "$TSV")

echo "downloaded=$got already-present=$skipped failed=$failed"
[[ $failed -eq 0 ]]
