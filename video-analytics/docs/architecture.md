# Architecture

## Data flow

```text
RTSP / file / webcam
        |
        v
  ingestion manager  (polls PostgreSQL for streams with status=running)
        |
        |  sample to target FPS, JPEG encode, maxlen-bounded stream
        v
  Redis Stream  frames:{stream_id}
        |
        |  consumer group "workers", XREADGROUP
        v
  detection worker  (ONNX YOLO, run-to-run latest-frame semantics)
        |
        |  JSON list of normalized detections
        v
  Redis Stream  detections
        |
        |  consumer group "eventproc", ACK after DB commit
        v
  event processor
    |-- IoU tracker (class-aware, TTL) + dedup
    |-- rule engine (zone, count, dwell, cooldown)
    |-- batched PostgreSQL writes
    |-- webhook dispatcher (retry with backoff)
    `-- Redis pub/sub: live frames/alerts
        |
        v
  FastAPI  --- REST + WebSocket ---> Next.js dashboard
        |
        +--> Prometheus --> Grafana
```

## Components

### Ingestion

`services/ingestion/ingestion.py` opens a source with OpenCV, samples frames at
`target_fps`, encodes JPEG, writes the latest frame to the Redis hash
`latest:{stream_id}` with a TTL, and publishes to `frames:{stream_id}` with
`MAXLEN ~ MAX_STREAM_LEN`. It reconnects with exponential backoff and jitter and
updates `streams.health` through a callback.

`services/ingestion/manager.py` polls the database every
`MANAGER_POLL_SECONDS` for streams whose desired state is `running`, starts one
ingestor thread per stream, stops removed/stopped streams, and deletes the
latest-frame cache on stop.

### Detection worker

`services/worker/detector.py` consumes frames through the `workers` consumer
group. It:

- drops and ACKs frames older than `STALE_THRESHOLD_MS` (latency bound);
- decodes JPEG and runs the selected detector backend;
- normalizes boxes to `[0, 1]` coordinates;
- publishes the detection batch to the `detections` stream;
- ACKs only after successful publish;
- retries failed messages and dead-letters after `MAX_DELIVERY_ATTEMPTS`;
- reclaims pending messages from crashed consumers with `XAUTOCLAIM`;
- refreshes stream length/lag gauges and processed FPS.

Backends: `onnx` (default), `mock` (deterministic-ish local UI testing), and
`yolo` (optional Ultralytics/PyTorch). The ONNX loader supports YOLOv5-style
`[1, N, 85]` and YOLOv8-style `[1, 84, N]` outputs and FP16 or FP32 input
models.

### Event processor

`services/event-processor/processor.py` consumes `detections` through the
`eventproc` consumer group. For each batch it:

1. refreshes enabled rules from PostgreSQL on a short interval;
2. folds detections into per-stream IoU tracks so one object is logged once;
3. applies zone/count/dwell/cooldown rules;
4. appends events to a bounded buffer;
5. commits buffered events in batches, then commits alerts in a separate
   transaction;
6. ACKs messages only after the event commit;
7. publishes live updates and submits webhook deliveries after alert commit.

If the buffer reaches `DB_BUFFER_MAX`, the oldest buffered event is dropped
(counted by reason) rather than growing memory without bound. On a database
failure the buffer is retained and messages stay pending. Malformed detection
payloads are retried and then moved to `dead-letter`; database write failures
do not currently dead-letter, they keep the bounded buffer and pending ACKs for
retry. Delivery is therefore at-least-once: a crash after commit and before ACK
can duplicate an event.

### API

`services/api/main.py` is a FastAPI app with:

- JWT login for admin users, seeded on startup;
- public GET endpoints for dashboard viewing; mutations require auth;
- stream CRUD and start/stop, which update desired state for the manager;
- latest frame endpoint backed by Redis `latest:{stream_id}`;
- cursor-paginated events and alerts;
- rules CRUD with zone/polygon validation and webhook URL validation;
- WebSocket endpoints for live detections and alerts;
- a Redis pub/sub subscriber that fans messages out to WebSockets;
- request-ID middleware, structured error envelopes, per-route metrics, and a
  Redis-backed login rate limiter;
- `/health` with PostgreSQL and Redis checks, plus `/metrics`. The alert
  subscriber is started during API lifespan, but health does not yet assert its
  liveness.

### Dashboard

The Next.js app polls the latest JPEG for each running stream, draws detection
overlays on a canvas, provides polygon zone drawing and rule creation, filters
and paginates events, and receives alerts over WebSocket. Authentication uses
the API login token stored client-side.

## Reliability properties

- **Bounded queues**: Redis `MAXLEN` on frame/detection streams and a bounded
  DB buffer.
- **Event ACK-after-commit**: pending messages remain reclaimable on DB failure;
  alert persistence failures are not retried separately.
- **Stale-work rejection**: capture timestamps are compared before inference.
- **Crash recovery**: `XAUTOCLAIM` in both consumers.
- **Backpressure**: the manager keeps one ingestor per stream; workers read in
  small batches; dashboard polling is capped by the frame endpoint.
- **Idempotent demo**: migration + seed jobs are safe to rerun.

## Security boundaries

- Stream URLs are restricted to allowed schemes/extensions; private/loopback
  destinations are blocked unless explicitly allow-listed for the Compose demo.
- Mutating API routes require a signed JWT; the default admin password is for
  local use only and must be changed.
- CORS is restricted to configured dashboard origins.
- The demo is not intended to be exposed directly to the public internet.

## Deployment

`infra/docker-compose.yml` runs Redis, PostgreSQL, Alembic migrations, the demo
seed, sample bootstrap, MediaMTX, a fake RTSP camera, ingestion, worker, event
processor, API, dashboard, Prometheus, and Grafana. The `docker-compose.yml` in
this directory includes the infra file so `docker compose up --build` works
from `video-analytics/`.

## Known limitations

- The Docker stack has been run end to end from a copy outside OneDrive. The
  original OneDrive checkout cannot be used as a Docker build context.
- The local functional pipeline uses fakeredis and SQLite, so it does not
  validate real Redis/PostgreSQL failure behavior.
- No GPU is available; ONNX inference is CPU-only. The 4-stream/10 FPS p95
  target is not met on this hardware (see `benchmarks/results/`).
- Processing is at-least-once: `XAUTOCLAIM` and a post-commit ACK failure can
  duplicate events or alerts.
- The provided sample is a short looping clip; real RTSP camera behavior is
  untested here.
