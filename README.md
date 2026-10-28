# Pehredaar — local video + detection base

After-hours shop security prototype: **Mac webcam → MediaMTX (RTSP) → Frigate (person detect + zones) → Mosquitto (MQTT) → Python brain → Bolna call**.

Video/detection stack runs in Docker; the brain runs natively on the Mac.

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

## Brain (alert → vision → call)

Runs on the Mac host (not Docker). Needs Frigate + Mosquitto already up.

```bash
cd ~/Desktop/pehredaar
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill GEMINI_API_KEY / GROQ_API_KEY / Bolna / OWNER_PHONE
python -m brain.main
```

`DRY_RUN=true` (default) prints the Bolna payload and never places a call.

### Fake alert (no camera)

With the brain running in another terminal:

```bash
chmod +x scripts/send_fake_alert.sh
./scripts/send_fake_alert.sh
# send again — second publish is suppressed (same review id / incident dedupe)
./scripts/send_fake_alert.sh
```

You should see a vision verdict JSON, then a `DRY_RUN Bolna payload` with `threat_hi` in Hindi. Only the first send triggers a call path.

### Live webcam end-to-end

1. `./scripts/start_camera.sh` + `docker compose up -d`
2. `python -m brain.main`
3. Walk into frame → same verdict + DRY_RUN payload (or a real call)

### Turn DRY_RUN off (real phone call)

In `.env`:

```bash
DRY_RUN=false
BOLNA_API_KEY=...
BOLNA_AGENT_ID=...
OWNER_PHONE=+91XXXXXXXXXX   # E.164
GEMINI_API_KEY=...          # or rely on GROQ_API_KEY / fail-safe
```

Restart the brain, then `./scripts/send_fake_alert.sh` (or walk in). Your phone should ring; the Bolna agent speaks `threat_hi`.

Incidents append to `logs/incidents.jsonl`.

## Stop

```bash
# Terminal 1: Ctrl+C (stops ffmpeg; stops MediaMTX only if this script started it)
# Brain: Ctrl+C
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
├── scripts/start_camera.sh      # MediaMTX + ffmpeg (webcam or --video loop)
├── scripts/send_fake_alert.sh   # republish tests/fixtures/review_new.json
├── brain/                       # MQTT → vision → Bolna
├── config/config.yml
├── mosquitto/mosquitto.conf
├── tests/fixtures/review_new.json
├── media/                       # recordings (gitignored)
├── logs/incidents.jsonl         # gitignored
└── README.md
```
