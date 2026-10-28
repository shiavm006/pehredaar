#!/usr/bin/env bash
# Publish Mac webcam (or a looped test video) as RTSP for Frigate.
# Stream URL: rtsp://localhost:8554/shopcam
set -euo pipefail

RTSP_URL="${RTSP_URL:-rtsp://127.0.0.1:8554/shopcam}"
CAMERA_INDEX="${CAMERA_INDEX:-0}"
WIDTH="${WIDTH:-1280}"
HEIGHT="${HEIGHT:-720}"
FPS="${FPS:-30}"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/start_camera.sh                  # FaceTime / built-in webcam
  ./scripts/start_camera.sh --video FILE     # loop a video file (repeatable tests)
  ./scripts/start_camera.sh -v FILE

Env overrides: CAMERA_INDEX, WIDTH, HEIGHT, FPS, RTSP_URL, MTX_CONF
EOF
}

VIDEO_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    -v|--video)
      VIDEO_FILE="${2:-}"
      if [[ -z "$VIDEO_FILE" ]]; then
        echo "Missing path after $1" >&2
        usage >&2
        exit 1
      fi
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing '$1'. Install with: brew install $1" >&2
    exit 1
  fi
}

need mediamtx
need ffmpeg

MTX_CONF="${MTX_CONF:-/opt/homebrew/etc/mediamtx/mediamtx.yml}"
if [[ ! -f "$MTX_CONF" ]]; then
  MTX_CONF="$(brew --prefix)/etc/mediamtx/mediamtx.yml"
fi

if ! lsof -nP -iTCP:8554 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Starting MediaMTX on :8554 (config: ${MTX_CONF}) ..."
  mediamtx "$MTX_CONF" >/tmp/pehredaar-mediamtx.log 2>&1 &
  echo $! >/tmp/pehredaar-mediamtx.pid
  sleep 1
else
  echo "Port 8554 already in use — reusing existing MediaMTX (or other RTSP server)."
fi

cleanup() {
  echo ""
  echo "Stopping ffmpeg publisher..."
  if [[ -f /tmp/pehredaar-mediamtx.pid ]]; then
    MTX_PID="$(cat /tmp/pehredaar-mediamtx.pid)"
    if kill -0 "$MTX_PID" 2>/dev/null; then
      kill "$MTX_PID" 2>/dev/null || true
    fi
    rm -f /tmp/pehredaar-mediamtx.pid
  fi
}
trap cleanup EXIT INT TERM

publish_webcam() {
  local input="${CAMERA_INDEX}:none"
  echo "Publishing webcam [${input}] → ${RTSP_URL}"
  echo "Press Ctrl+C to stop."
  echo ""
  echo "If ffmpeg fails with camera permission errors:"
  echo "  System Settings → Privacy & Security → Camera → enable for Terminal/Cursor"
  echo ""

  ffmpeg -hide_banner -loglevel info \
    -f avfoundation \
    -pixel_format uyvy422 \
    -framerate "${FPS}" \
    -video_size "${WIDTH}x${HEIGHT}" \
    -i "${input}" \
    -an \
    -c:v libx264 \
    -preset ultrafast \
    -tune zerolatency \
    -bf 0 \
    -pix_fmt yuv420p \
    -g $((FPS * 2)) \
    -f rtsp \
    -rtsp_transport tcp \
    "${RTSP_URL}"
}

publish_video() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    echo "Video file not found: $file" >&2
    exit 1
  fi
  echo "Looping video [${file}] → ${RTSP_URL}"
  echo "Press Ctrl+C to stop."
  echo ""

  # -stream_loop -1 + -re = endless real-time replay for repeatable person tests.
  ffmpeg -hide_banner -loglevel info \
    -re \
    -stream_loop -1 \
    -i "${file}" \
    -an \
    -c:v libx264 \
    -preset ultrafast \
    -tune zerolatency \
    -bf 0 \
    -pix_fmt yuv420p \
    -g $((FPS * 2)) \
    -f rtsp \
    -rtsp_transport tcp \
    "${RTSP_URL}"
}

if [[ -n "$VIDEO_FILE" ]]; then
  publish_video "$VIDEO_FILE"
else
  publish_webcam
fi
