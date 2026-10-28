# Real-Time Video Analytics Platform

A self-hosted, multi-stream video analytics pipeline: ingest live video, run
object detection on sampled frames, turn detections into events and alerts,
and watch everything on a live dashboard with metrics.

This is a portfolio project focused on **backend systems and computer vision
engineering**: bounded queues, backpressure, frame dropping, consumer groups,
automatic reconnect, observability, and a real-time UI.

---

## Architecture

```text
[Video source / RTSP / file]
        |
  [Ingestion Service] --frames--> Redis Stream: frames:{stream_id}
        |                              |
        |                     [Detection Workers] (consumer group, XREADGROUP)
        |                              |
        |                     Redis Stream: detections
        |                              |
        |                     [Event Processor] ---- pub/sub ----> API WS clients
        |                        |          |
        |                  [PostgreSQL]  [Rule Engine] --> alerts (DB + pub/sub)
        |                        |          |
        +--------------> [API Gateway (REST + WebSocket)]
                                   |
                          [Next.js Dashboard]

  All services --> Prometheus --> Grafana
```

See `docs/architecture.md` and `docs/design-decisions.md` for detail.

## Features

- Register/start/stop/delete streams via REST API and UI
- Ingest RTSP streams and looped video files
- YOLO object detection via ONNX Runtime (with a mock backend for dev/testing)
- Redis Streams pipeline with consumer groups, bounded queues, stale-frame dropping
- Event persistence in PostgreSQL (batch writes, dedup)
- IoU track deduplication, zone/count/dwell rules, cooldowns, and webhook alerts
- Alerts in the UI (WebSocket) and stored in the DB
- Live dashboard with canvas overlays drawn from detection JSON
- Prometheus metrics for every service; provisioned Grafana overview dashboard
- Automatic reconnect with exponential backoff and jitter
- Worker/event-processor crash recovery via `XAUTOCLAIM`

---

## Quick Start

```bash
docker compose up --build
```

> **Windows/OneDrive:** Docker BuildKit cannot read OneDrive cloud-placeholder
> files and fails with `ERROR: invalid file request ...`. Run Compose from a
> copy of the repository outside OneDrive. The stack and smoke test were
> verified from such a copy.

Then open:

| Service    | URL                                         |
| ---------- | ------------------------------------------- |
| Dashboard  | http://localhost:3000                       |
| API docs   | http://localhost:8000/docs                  |
| Prometheus | http://localhost:9090                       |
| Grafana    | http://localhost:3001 (default admin/admin) |

The stack seeds a demo stream and rule automatically. MediaMTX publishes a
looped sample clip at `rtsp://mediamtx:8554/demo`, the ingestion manager starts
the demo stream, and frames flow through the pipeline. Login to the dashboard
with the seeded admin credentials from `.env` (`admin@example.com` / `admin` by
default). GET endpoints remain public so the demo frame/event views work
without a login; mutations require the admin token.

If the sample download is unavailable, generate a local fallback clip:

```bash
python scripts/fetch_sample.py samples/sample.avi
```

The script prefers OpenCV's `vtest.avi` (people walking), so the real YOLO
backend has something to detect.

### Add or edit streams

1. Use **Add stream** in the dashboard.
2. For a local file, use the path mounted into the ingestion container
   (`/samples/sample.avi` when using Compose).
3. Click **start**; open the zone editor on a stream to draw a polygon and
   create a rule.

The ingestion service runs as a **manager**: it polls the database for streams
with status `running` and starts/stops an ingestor per stream. This makes the
API/UI start/stop controls effective without restarting containers.

---

## Local Development

### Full local e2e without Docker

The fastest check on Windows without Docker uses fakeredis and SQLite while
running the real ingestion, worker, and event-processor classes:

```bash
python scripts/local_pipeline.py --backend mock --seconds 10
python scripts/local_pipeline.py --backend onnx --seconds 12
```

For ONNX, create a Python 3.11+ virtual environment and install
`services/worker/requirements.txt`; the model is downloaded on first use. This
is a functional smoke test, not a benchmark.

### Full local dev stack

Requirements: Python 3.11+, Redis, PostgreSQL, Node 20+.

```bash
# 1. Python deps
pip install -r requirements-dev.txt
pip install -r services/event-processor/requirements.txt
pip install -r services/api/requirements.txt
pip install -r services/ingestion/requirements.txt
pip install -r services/worker/requirements.txt

# 2. Start Redis and Postgres (Docker or local installs)

# 3. Initialise the database
cd services/event-processor && alembic upgrade head && cd ../..

# 4. Run services in separate terminals
cd services/event-processor && python run.py
cd services/worker && DETECTOR_BACKEND=mock python run.py
cd services/ingestion && python run.py --manager
cd services/api && uvicorn main:app --reload --port 8000

# 5. Dashboard
cd web && npm install && npm run dev
```

Set `DETECTOR_BACKEND=mock` to run the worker without ONNX Runtime/models.
For real detection, use `DETECTOR_BACKEND=onnx` (the worker downloads
`yolov5n.onnx` on first use) or `DETECTOR_BACKEND=yolo` with the optional
`ultralytics` extra.

### Configuration

All config is environment-based. See `.env.example`. Key variables:

| Variable              | Default                        | Used by        |
| --------------------- | ------------------------------ | -------------- |
| `REDIS_HOST`/`PORT`   | `localhost:6379`               | all            |
| `POSTGRES_DSN`        | `postgresql://user:pass@...`   | ep, api, ingest|
| `MAX_FPS`             | `10`                           | ingestion      |
| `MAX_STREAM_LEN`      | `1000`                         | ingestion      |
| `STALE_THRESHOLD_MS`  | `300`                          | worker         |
| `DETECTOR_BACKEND`    | `onnx` (`onnx`\|`mock`\|`yolo`)| worker         |
| `MODEL_PATH`          | `yolov5n.onnx`                 | worker         |
| `JWT_SECRET`          | `dev-only-change-me`           | api            |
| `ALLOW_PRIVATE_HOSTS` | `mediamtx`                     | api            |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000`        | web            |

`ALLOW_PRIVATE_HOSTS` is a comma-separated allow-list of private hostnames/IPs
that may be used as stream sources. The default only allows the Compose demo
host; do not allow arbitrary private hosts in a public deployment.

---

## API Reference (v1)

| Method | Path                          | Purpose                              |
| ------ | ----------------------------- | ------------------------------------ |
| POST   | `/api/auth/login`             | Obtain an admin JWT                  |
| POST   | `/api/streams`                | Register a stream (URL validated)    |
| GET    | `/api/streams`                | List streams                         |
| POST   | `/api/streams/{id}/start`     | Start ingestion                      |
| POST   | `/api/streams/{id}/stop`      | Stop ingestion                       |
| DELETE | `/api/streams/{id}`           | Remove stream and dependent rows     |
| GET    | `/api/streams/{id}/frame`     | Latest cached JPEG frame             |
| GET    | `/api/events`                 | Query events (`stream_id`, `class`, `from_ts`, `to_ts`, `cursor`, `limit`) |
| POST   | `/api/rules`                  | Create rule                          |
| GET    | `/api/rules`                  | List rules                           |
| PATCH  | `/api/rules/{id}`             | Update/disable rule                  |
| DELETE | `/api/rules/{id}`             | Delete rule                          |
| GET    | `/api/alerts`                 | List alerts (cursor pagination)      |
| GET    | `/api/health`                 | Health/readiness details             |
| GET    | `/metrics`                    | Prometheus metrics                   |
| WS     | `/ws/streams/{id}`            | Live detections                      |
| WS     | `/ws/alerts`                  | Live alerts                          |

Mutations require `Authorization: Bearer <token>` when `AUTH_ENABLED=1` (the
default). Log in with `ADMIN_EMAIL`/`ADMIN_PASSWORD`; GET routes stay public for
the demo dashboard.

Example:

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"admin"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -X POST localhost:8000/api/streams \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"file-demo","source_url":"/samples/sample.avi"}'
```

Stream URLs are validated (allow-list: `rtsp`, `rtmp`, `file`, local video
paths) and private/loopback hosts are blocked to mitigate SSRF, except for
explicit `ALLOW_PRIVATE_HOSTS` entries.

Events/alerts use cursor envelopes:

```json
{"items": [], "next_cursor": null}
```

Errors use:

```json
{"error": {"code": "validation_error", "message": "..."}}
```

---

## Metrics

Each service exposes Prometheus metrics:

- Ingestion: `frames_ingested_total`, `frames_published_total`,
  `reconnect_attempts_total`, `stream_fps{stream,direction}`,
  `stream_status{stream}`
- Worker: `frames_processed_total`, `frames_dropped_total{stream,reason}`,
  `detections_published_total`, `inference_duration_seconds`,
  `postprocess_duration_seconds`, `redis_consumer_lag`
- Event processor: `ep_events_written_total`, `ep_dedup_hits_total`,
  `ep_alerts_fired_total`, `ep_events_dropped_total`,
  `ep_db_write_errors_total`, `ep_messages_dead_lettered_total`,
  `ep_db_write_duration_seconds`, `ep_pipeline_latency_seconds`,
  `ep_active_tracks`
- API: `api_http_requests_total`, `api_http_request_duration_seconds`,
  `api_rate_limited_total`, `api_websocket_messages_total`

The `ep_` and `api_` prefixes keep metric names unique when tests import
multiple services in one Python process. Grafana panels use these names.

---

## Benchmarks

The load-test harness lives in `benchmarks/load_test.py`:

```bash
python benchmarks/load_test.py --streams 4 --seconds 60 --fps 10
```

**No container benchmark results are recorded yet.** The functional Compose
smoke test now passes, but it is not a capacity measurement. The PRD target
(4 streams at 10 FPS, p95 end-to-end < 500 ms, <2% drops) is not claimed. Add
measured results under `benchmarks/results/` and fill in a table only after
running the harness on the target hardware.

---

## Testing

```bash
pip install -r requirements-dev.txt
pip install -r services/event-processor/requirements.txt
pip install -r services/api/requirements.txt
pip install -r services/ingestion/requirements.txt
pip install -r services/worker/requirements.txt
pytest -q
python -m ruff check services scripts benchmarks
python -m ruff format --check services scripts benchmarks
cd web && npm run typecheck && npm run build
```

Measured on 2026-10-26 (Windows, Python 3.12.4, Node 22.19.0):

- `pytest -q`: **44 passed**
- `ruff check services scripts benchmarks`: passed
- `ruff format --check services scripts benchmarks`: passed
- `npm run typecheck`: passed
- `npm run build`: passed (4 static routes generated)
- `docker compose -f docker-compose.yml config`: valid
- `docker compose up --build`: passed from a non-OneDrive copy; API, event
  processor, worker, ingestion, Postgres, Redis, Prometheus, Grafana, and web
  healthy
- `scripts/smoke.sh`: **PASS**: API health, dashboard, demo stream, 98,271-byte
  frame, 5 events, 5 alerts
- Admin login returns a JWT; unauthenticated stream creation returns 401
- Prometheus targets all up; web/Prometheus/Grafana return HTTP 200
- Real ONNX Runtime 1.20.1 in an isolated venv: **5 detections** on one
  `vtest.avi` frame (3 people, 1 car, 1 truck)
- Local ONNX pipeline: 61 frames / 18 events over 12 seconds with fakeredis +
  SQLite (functional smoke, not a capacity result)

The full-stack run and smoke test were executed from a copy outside OneDrive.
The original OneDrive path still cannot be used as a Docker build context.
Full-stack benchmarks, browser UI/WebSocket interaction checks, and rendered
Grafana panels remain unverified.

CI (`.github/workflows/ci.yml`) runs tests and ruff on every push/PR.

---

## Repository Structure

```text
video-analytics/
  services/
    ingestion/       # frame capture, sampling, JPEG encode, publish
    worker/          # ONNX YOLO detection, consumer group, stale-frame drop
    event-processor/ # tracker, dedup, DB batch writes, rules, webhooks, pub/sub
    api/             # FastAPI REST + WebSocket + /metrics
  web/               # Next.js dashboard
  infra/             # docker-compose, prometheus, grafana, mediamtx
  benchmarks/        # load test script + results
  scripts/           # sample fetch, local e2e, Docker smoke
  docs/              # architecture, design decisions, status
```

Alembic migrations live in `services/event-processor/migrations/`.

## Design Decisions

Short version (full detail in `docs/design-decisions.md`):

- **Redis Streams over Kafka**: consumer groups + bounded streams, trivial to
  run locally; Kafka is stronger at scale but heavy for a 4-stream demo.
- **Client-side overlays**: send detection JSON, draw on canvas; saves bandwidth.
- **ONNX Runtime**: portable CPU/GPU and a clear phase-2 optimization path.
- **Drop stale frames + latest-frame-wins**: bounds latency under overload
  instead of growing queues forever.
- **Batch DB writes + IoU dedup**: one object is not logged hundreds of times.
- **ACK after commit**: a DB failure leaves messages pending for retry instead
  of silently losing events.
- **DB-backed stream manager**: start/stop from the UI without restarts.

## Phase 2 (Optional)

- Dynamic batching across streams in the worker
- TensorRT / OpenVINO / INT8 quantization with before/after benchmarks
- KEDA/HPA autoscaling on queue length

## License

MIT
