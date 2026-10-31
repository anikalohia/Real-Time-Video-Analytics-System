# Real-Time Video Analytics Platform

A self-hosted, multi-stream video analytics pipeline: ingest live video, run
object detection on sampled frames, turn detections into events and alerts,
and watch everything on a live dashboard with metrics.

This is a portfolio project focused on **backend systems and computer vision
engineering**: bounded queues, backpressure, frame dropping, consumer groups,
automatic reconnect, observability, and a real-time UI.

**Status:** working end-to-end via Docker Compose, 44 tests passing, CPU-only
capacity baseline measured below. Not production-hardened.

## Demo

![Dashboard with live YOLOv5n detections, events, and alerts](video-analytics/docs/assets/dashboard.png)

| Live detection overlay | Grafana pipeline metrics |
| --- | --- |
| ![YOLOv5n detections on the demo stream](video-analytics/docs/assets/stream.png) | ![Grafana overview dashboard](video-analytics/docs/assets/grafana.png) |

![Animated demo of the live dashboard](video-analytics/docs/assets/demo.gif)

[Watch the MP4 demo](video-analytics/docs/assets/demo.mp4) · [API docs screenshot](video-analytics/docs/assets/api-docs.png)

The demo loops a sample RTSP clip through MediaMTX, runs YOLOv5n on sampled
frames, and streams detection JSON to the dashboard over WebSocket.

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

See [`architecture.md`](video-analytics/docs/architecture.md),
[`design-decisions.md`](video-analytics/docs/design-decisions.md), and
[`STATUS.md`](video-analytics/docs/STATUS.md) for detail.

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
- Automatic ingest reconnect with exponential backoff and jitter
- Worker/event-processor crash recovery via `XAUTOCLAIM`

---

## Quick Start

All commands below run from `video-analytics/` unless noted otherwise.

```bash
cd video-analytics
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

The load-test harness lives in `benchmarks/load_test.py`. Results below were
measured on 2026-10-31 from the Docker Compose stack on Windows 11
(Docker Desktop/WSL2, 12 threads, CPU-only YOLOv5n, no GPU). The generator ran
inside the Compose network to avoid host-network latency.

| Scenario | Published | Processed | Stale/dropped | p50 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 4 streams, 10 FPS target, 1 worker | 888 | 158 | 730 (82.2%) | 468.4 ms | 806.1 ms | 876.6 ms |
| 2 streams, 3 FPS, 2 workers | 354 | 259 | 95 (26.8%) | 440.4 ms | 710.9 ms | 798.6 ms |

Standalone YOLOv5n inference at 640×640: **p50 230.1 ms**, **p95 650.1 ms**,
mean **288.1 ms** over 10 minutes. A single 5 FPS stream inside Docker measured
p50 **451.9 ms**, p95 **635.4 ms**, p99 **727.7 ms**.

**Interpretation:** under overload the pipeline sheds stale frames instead of
growing queues without bound. The 4-stream run published only ~15 FPS aggregate
on this CPU, so it is an overload/backpressure test, not a valid 40 FPS NFR
validation. The PRD target (4 streams at 10 FPS, p95 <500 ms, <2% drops) is
**not met on this CPU-only setup**. A GPU or smaller model is needed for that
target. See [raw benchmark notes](video-analytics/benchmarks/results/2026-10-31-cpu-only.md).

To reproduce inside the Compose network:

```bash
docker run --rm --network video-analytics_default \
  --entrypoint python \
  -v "$PWD/benchmarks:/bench:ro" \
  video-analytics-worker \
  /bench/load_test.py --redis-host redis --streams 4 --seconds 60 --fps 10
```

Adjust the network name if you set `COMPOSE_PROJECT_NAME`.

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

Repeated on 2026-10-31:

- Dashboard rendered the live demo frame, canvas overlays, event timeline, and
  alert panel; WebSocket updates were flowing.
- Grafana rendered the provisioned overview dashboard with live pipeline panels.
- Load tests completed; see [Benchmarks](#benchmarks).

The full-stack run and smoke test were executed from a copy outside OneDrive.
The original OneDrive path still cannot be used as a Docker build context.

CI (`.github/workflows/ci.yml` at the repository root) runs Python tests, ruff,
the web typecheck/build, and Compose config validation on every push/PR.

---

## Repository Structure

```text
.github/workflows/    # CI
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
  docs/              # architecture, design decisions, status, demo assets
```

Alembic migrations live in `video-analytics/services/event-processor/migrations/`.

## Design Decisions

Short version (full detail in
[`design-decisions.md`](video-analytics/docs/design-decisions.md)):

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

## Known Limitations

- CPU-only deployment does not meet the 4-stream/10 FPS p95 target; see
  [Benchmarks](#benchmarks).
- Processing is at-least-once. A rare failure after the DB commit but before the
  Redis ACK can produce duplicate events or alerts.
- The dashboard WebSocket clients do not yet auto-reconnect after an API restart;
  refresh the page to restore live updates.
- Default credentials and `JWT_SECRET` are for local demo use; change them
  before exposing the stack to any untrusted network.
- `NEXT_PUBLIC_API_URL` and `CORS_ORIGINS` are build-time/deployment settings;
  the defaults point at localhost.
- Physical RTSP cameras and production failure/chaos scenarios are untested.

## License

MIT — see [LICENSE](LICENSE).
