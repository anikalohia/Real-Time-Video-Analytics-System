# Real-Time Video Analytics Platform

A self-hosted, multi-stream video analytics pipeline: ingest live video, run
object detection on sampled frames, turn detections into events and alerts,
and watch everything on a live dashboard with metrics.

This is a portfolio project focused on **backend systems and computer vision
engineering**: bounded queues, backpressure, frame dropping, consumer groups,
automatic reconnect, observability, and a real-time UI.

---

## Architecture

```
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
- Zone-based, count-based and dwell-time rules with cooldowns
- Alerts in the UI (WebSocket) and stored in the DB
- Live dashboard with canvas overlays drawn from detection JSON
- Prometheus metrics for every service; Grafana provisioning
- Automatic reconnect with exponential backoff and jitter
- Worker crash recovery via `XAUTOCLAIM`

---

## Quick Start

```bash
docker compose up --build
```

Then open:

| Service    | URL                        |
| ---------- | -------------------------- |
| Dashboard  | http://localhost:3000      |
| API docs   | http://localhost:8000/docs |
| Prometheus | http://localhost:9090      |
| Grafana    | http://localhost:3001 (default admin/admin) |

### Add your first stream

1. Generate a sample video (no camera needed):

   ```bash
   python scripts/make_sample.py samples/sample.mp4 --seconds 20
   ```

2. In the dashboard, add a stream:
   - name: `demo`
   - source: `sample.mp4`  (path inside the ingestion container; mounted from `./samples`)
3. Click **start** (or call the API), and detections/events will appear.

The ingestion service runs as a **manager**: it polls the database for streams
with status `running` and starts/stops an ingestor per stream. This makes the
API/UI start/stop controls immediately effective without restarting containers.

---

## Local Development (no Docker)

Requirements: Python 3.11+, Redis, PostgreSQL, Node 20+.

```bash
# 1. Python deps (per service, or use the dev requirements)
pip install -r requirements-dev.txt
pip install -r services/worker/requirements.txt

# 2. Start Redis and Postgres (e.g. via docker or a local install)

# 3. Run each service in its own terminal
cd services/event-processor && python run.py    # creates DB schema
cd services/api && uvicorn main:app --reload --port 8000
cd services/worker && DETECTOR_BACKEND=mock python run.py
cd services/ingestion && python run.py --manager

# 4. Dashboard
cd web && npm install && npm run dev
```

Set `DETECTOR_BACKEND=mock` to run the worker without ONNX Runtime/models.
For real detection, download `yolov5n.onnx` (the worker downloads it on first
use) or use `DETECTOR_BACKEND=yolo` with the optional `ultralytics` extra.

### Configuration

All config is environment-based. See `.env.example`. Key variables:

| Variable              | Default                        | Used by        |
| --------------------- | ------------------------------ | -------------- |
| `REDIS_HOST`/`PORT`   | `localhost:6379`               | all            |
| `POSTGRES_DSN`        | `postgresql://user:pass@...`   | ep, api, ingest|
| `SOURCE_URL`          | –                              | ingestion      |
| `MAX_FPS`             | `10`                           | ingestion      |
| `MAX_STREAM_LEN`      | `1000`                         | ingestion      |
| `STALE_THRESHOLD_MS`  | `300`                          | worker         |
| `DETECTOR_BACKEND`    | `onnx` (`onnx`\|`mock`\|`yolo`)| worker         |
| `MODEL_PATH`          | `yolov5n.onnx`                 | worker         |
| `JWT_SECRET`          | `dev-secret-change-me`         | api            |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000`        | web            |

---

## API Reference (v1)

| Method | Path                       | Purpose                              |
| ------ | -------------------------- | ------------------------------------ |
| POST   | `/api/streams`             | Register a stream (URL validated)    |
| GET    | `/api/streams`             | List streams                         |
| POST   | `/api/streams/{id}/start`  | Start ingestion                      |
| POST   | `/api/streams/{id}/stop`   | Stop ingestion                       |
| DELETE | `/api/streams/{id}`        | Remove stream                        |
| GET    | `/api/events`              | Query events (stream, class, from, to, cursor, limit) |
| POST   | `/api/rules`               | Create rule                          |
| GET    | `/api/rules`               | List rules                           |
| PATCH  | `/api/rules/{id}`          | Update/disable rule                  |
| GET    | `/api/alerts`              | List alerts                          |
| GET    | `/api/health`              | Health check                         |
| GET    | `/metrics`                 | Prometheus metrics                   |
| WS     | `/ws/streams/{id}`         | Live detections                      |
| WS     | `/ws/alerts`               | Live alerts                          |

Example:

```bash
curl -X POST localhost:8000/api/streams \
  -H "Content-Type: application/json" \
  -d '{"name":"demo","source_url":"sample.mp4"}'
```

Stream URLs are validated (allow-list: `rtsp`, `rtmp`, `file`, local video
paths) and private/loopback hosts are blocked to mitigate SSRF.

---

## Metrics

Each service exposes Prometheus metrics:

- `stream_fps{stream}` / `frames_ingested_total`, `frames_published_total`
- `frames_dropped_total{stream, reason}`
- `inference_duration_seconds`, `postprocess_duration_seconds` (histograms)
- `frames_processed_total{stream}`, `detections_published_total`
- `events_written_total`, `db_write_duration_seconds`
- `alerts_fired_total{rule}`
- `stream_status{stream}` (1 connected / 3 failed)

---

## Benchmarks

Fill this in after running the load tests (`benchmarks/load_test.py`). The PRD
targets: ≥4 streams at 10 FPS, p95 end-to-end < 500 ms, <2% drop at 2× load.

| Streams | Target FPS | p50 (ms) | p95 (ms) | p99 (ms) | Drop % | CPU | Mem | Notes |
| ------- | ---------- | -------- | -------- | -------- | ------ | --- | --- | ----- |
| 1       | 10         |          |          |          |        |     |     |       |
| 2       | 10         |          |          |          |        |     |     |       |
| 4       | 10         |          |          |          |        |     |     |       |
| 8       | 10         |          |          |          |        |     |     |       |

Run:

```bash
python benchmarks/load_test.py --streams 4 --seconds 60 --fps 10
```

---

## Testing

```bash
pip install -r requirements-dev.txt
pip install -r services/worker/requirements.txt
pytest -q
```

- Unit tests: zone geometry, rule evaluation, URL validation, worker frame
  encode/decode, stale-frame dropping, normalized bboxes
- Integration tests: detections → DB persistence, dedup, rule firing, alert
  persistence, live pub/sub broadcast (uses `fakeredis` + SQLite)

CI (`.github/workflows/ci.yml`) runs tests and ruff on every push/PR.

---

## Repository Structure

```
video-analytics/
  services/
    ingestion/       # frame capture, sampling, JPEG encode, publish
    worker/          # ONNX YOLO detection, consumer group, stale-frame drop
    event-processor/ # dedup, DB batch writes, rule engine, pub/sub
    api/             # FastAPI REST + WebSocket + /metrics
  web/               # Next.js dashboard
  infra/             # docker-compose, prometheus, grafana
  benchmarks/        # load test script + results
  scripts/           # sample video generator
  docs/              # architecture, design decisions
```

## Design Decisions

Short version (full detail in `docs/design-decisions.md`):

- **Redis Streams over Kafka** — consumer groups + bounded streams, trivial to
  run locally; Kafka is stronger at scale but heavy for a 4-stream demo.
- **Client-side overlays** — send detection JSON, draw on canvas; saves bandwidth.
- **ONNX Runtime** — portable CPU/GPU and a clear phase-2 optimization path.
- **Drop stale frames + latest-frame-wins** — bounds latency under overload
  instead of growing queues forever.
- **Batch DB writes + dedup** — one object isn't logged hundreds of times.
- **DB-backed stream manager** — start/stop from the UI without restarts.

## Phase 2 (Optional)

- Dynamic batching across streams in the worker
- TensorRT / OpenVINO / INT8 quantization with before/after benchmarks
- KEDA/HPA autoscaling on queue length

## License

MIT
