# Pehredaar — local video + detection base

After-hours shop security prototype: **Mac webcam → MediaMTX (RTSP) → Frigate (person detect + zones) → Mosquitto (MQTT)**.

This step covers only the video/detection stack. No brain, vision check, or phone calls yet.

## Prerequisites

```bash
brew install ffmpeg mediamtx mosquitto   # mosquitto = host client (mosquitto_sub)
# Docker Desktop for Mac (Apple Silicon) running
```

### macOS camera permission

ffmpeg uses AVFoundation, so the app that launches `scripts/start_camera.sh` needs Camera access:

1. **System Settings → Privacy & Security → Camera**
2. Enable **Terminal**, **iTerm**, or **Cursor**
3. Quit and reopen that app after granting access

List devices: `ffmpeg -f avfoundation -list_devices true -i ""`  
FaceTime HD is usually index `0` (`CAMERA_INDEX=1 ./scripts/start_camera.sh` to override).

## Start

From this directory, use two terminals.

**Terminal 1 — RTSP publisher**

```bash
chmod +x scripts/start_camera.sh
./scripts/start_camera.sh
```

Webcam → `rtsp://localhost:8554/shopcam`. Leave it running.

For repeatable tests, loop a file instead of the webcam:

```bash
./scripts/start_camera.sh --video /path/to/person.mp4
```

**Terminal 2 — Mosquitto + Frigate**

```bash
docker compose up -d
docker compose logs -f frigate
```

Wait until the camera is up (no repeated ffmpeg reconnect errors).

### Frigate UI

- Local testing (no login): [http://localhost:5001](http://localhost:5001)
- Authenticated UI: [http://localhost:8971](http://localhost:8971)  
  First boot prints an admin password: `docker logs pehredaar-frigate 2>&1 | grep -A2 'Password:'`

Live view: **Cameras → shopcam**.

## MQTT test (start subscriber BEFORE walking into frame)

```bash
mosquitto_sub -h localhost -t 'frigate/reviews' -v
```

Then walk in front of the webcam (fill most of the frame). Expect a message with `"type": "new"` and `"severity": "alert"` (plus `shop_floor` in zones). In the Frigate UI → **Review**, open that item — clip and snapshot should be present.

Tip: for a repeatable run without standing up, stop the webcam publisher (Ctrl+C) and loop a person clip instead:

```bash
./scripts/start_camera.sh --video /path/to/person.mp4
```

## Stop

```bash
# Terminal 1: Ctrl+C (stops ffmpeg; stops MediaMTX only if this script started it)
docker compose down
```

Optional cleanup of recordings/DB (keeps `config/config.yml`):

```bash
rm -rf media/* config/*.db config/*.db-*
```

## Layout

```text
.
├── docker-compose.yml
├── scripts/start_camera.sh   # MediaMTX + ffmpeg (webcam or --video loop)
├── config/config.yml         # shopcam, person, shop_floor, MQTT
├── mosquitto/mosquitto.conf
├── media/                    # recordings & clips (gitignored)
└── README.md
```
