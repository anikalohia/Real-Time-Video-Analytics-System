# PRD and TRD: Real-Time Video Analytics Platform

Project type: SDE portfolio project (CV + backend systems). Timeline: 3-4 weeks. Owner: Anika Lohia.

---

# Part 1: Product Requirements Document (PRD)

## 1. Overview

A platform that ingests multiple live video streams, runs object detection on each frame in real time, turns detections into events (for example, person entered a zone, object count exceeded a limit), stores them, and shows everything on a live dashboard with alerts. Think of a small-scale, self-hosted version of what security and retail analytics products do.

## 2. Problem Statement

Camera feeds produce more data than humans can watch. Existing tools are either expensive SaaS or single-script demos that cannot handle several streams, slow consumers, or failures. This project builds a reliable, observable multi-stream pipeline that stays responsive under load.

## 3. Goals

- Process 2-4 concurrent video streams with live detection overlays.
- Keep end-to-end latency (frame captured to event on dashboard) low and measurable.
- Degrade gracefully under load by dropping frames instead of crashing or lagging forever.
- Expose clear metrics so bottlenecks can be found and fixed.
- Run the whole system with one command and deploy a public demo.

## 4. Non-Goals

- Training a new detection model (use a pretrained YOLO model).
- Face recognition or any biometric identification.
- Mobile apps, multi-tenant billing, or enterprise SSO.
- Hardware-specific optimization in v1 (that is phase two).

## 5. Target Users and Personas

- **Operator:** watches the dashboard, wants live view and alerts without noise.
- **Admin:** adds or removes streams, configures zones and alert rules.
- **Developer (secondary, for the portfolio audience):** reads the README and architecture, runs it locally, checks the benchmarks.

## 6. User Stories

1. As an admin, I can register a stream (RTSP URL or looped video file) and start or stop it from the UI.
2. As an operator, I can see a live view per stream with bounding boxes and labels.
3. As an operator, I can see a timeline of events and filter by stream, class, and time range.
4. As an admin, I can draw a zone on a stream and create a rule such as "alert if more than 3 people in zone for 10 seconds".
5. As an operator, I receive an alert in the UI (and optionally by webhook) when a rule fires.
6. As a developer, I can view live system metrics: FPS per stream, latency, queue depth, dropped-frame rate.
7. As an admin, I can see stream health (connected, reconnecting, failed) and the system recovers automatically from a dropped stream.

## 7. Functional Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| F1 | Register, start, stop, and delete streams via API and UI | Must |
| F2 | Ingest RTSP streams and looped video files | Must |
| F3 | Run object detection on sampled frames and publish detections | Must |
| F4 | Persist events with timestamp, stream, class, confidence, bounding box | Must |
| F5 | Live dashboard with video overlay and event feed over WebSocket | Must |
| F6 | Rule engine with zone-based and count-based alerts | Should |
| F7 | Alert delivery in UI and by webhook | Should |
| F8 | Event query API with filtering and pagination | Must |
| F9 | Metrics endpoint and Grafana dashboards | Must |
| F10 | Automatic reconnect with backoff for failed streams | Must |
| F11 | Short event clips or snapshots stored for alerts | Could |
| F12 | Basic authentication for the dashboard and API | Should |

## 8. Non-Functional Requirements

- **Latency:** p95 end-to-end under 500 ms per stream at 10 inference FPS (target; measure and report actual).
- **Throughput:** at least 4 streams at 10 FPS on a single consumer machine (CPU or modest GPU). Report the real ceiling.
- **Reliability:** a crashed worker or dropped stream must not stop other streams; recovery within 30 seconds.
- **Backpressure:** bounded queues; when consumers lag, drop oldest frames and count them.
- **Observability:** every service exposes Prometheus metrics and structured logs.
- **Portability:** `docker compose up` brings up the full system.
- **Security:** no hard-coded secrets, input validation on stream URLs, auth on the API.

## 9. Success Metrics

These are the numbers you will put on the resume.

- Streams supported per machine at target FPS.
- p50 and p99 end-to-end latency.
- Dropped-frame rate under 2x overload.
- Mean time to recover from a stream failure.
- Detection throughput before and after optimization (phase two).
- Test coverage and number of load-test scenarios.

## 10. Scope and Milestones

| Week | Deliverable |
| --- | --- |
| 1 | Ingestion service, detection worker, Redis Streams pipeline, single-stream end-to-end demo |
| 2 | Event storage, API, WebSocket dashboard with overlays, multi-stream support, reconnect logic |
| 3 | Rule engine and alerts, metrics and Grafana, load testing, bottleneck fixes |
| 4 | Docker Compose polish, README and architecture diagram, deployment, benchmark write-up |
| Phase 2 (optional) | ONNX/TensorRT export, dynamic batching, before/after benchmarks |

## 11. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| No GPU, inference too slow | Use YOLO nano model, sample frames (process every Nth frame), use ONNX Runtime on CPU |
| Streaming video in the browser is complex | Send annotated JPEG frames or MJPEG over WebSocket first; consider WebRTC only if time allows |
| Scope creep | Freeze scope at the Must items; Should and Could only after load tests pass |
| Hard to demo without real cameras | Loop sample videos through FFmpeg or MediaMTX as fake RTSP streams |
| Public demo cost | Deploy a lightweight demo with pre-recorded streams, or record a demo video as fallback |

## 12. Open Questions

- Run inference on CPU only, or target an available GPU?
- Annotated frames rendered server-side or overlays drawn client-side from detection JSON? (Recommended: client-side overlay, which saves bandwidth.)
- Redis Streams or Kafka? (Recommended: Redis Streams for v1; document the trade-off.)

---

# Part 2: Technical Requirements Document (TRD)

## 1. Architecture Overview

The system is a pipeline of small services connected by Redis Streams.

```
[Video source / RTSP]
        |
  [Ingestion Service]  --frames-->  Redis Stream: frames:{stream_id}
        |                                   |
        |                          [Detection Workers] (consumer group)
        |                                   |
        |                       Redis Stream: detections
        |                                   |
        |                          [Event Processor]
        |                           |           |
        |                    [PostgreSQL]   [Rule Engine] --> alerts
        |                           |           |
        +-----------------> [API Gateway (REST + WebSocket)] --> [Next.js Dashboard]

  All services --> Prometheus --> Grafana
```

## 2. Components

### 2.1 Ingestion Service (Python)

- Opens each stream with OpenCV or PyAV (FFmpeg backend).
- Samples frames at a configurable rate (default 10 FPS).
- Resizes and JPEG-encodes frames, then publishes to `frames:{stream_id}` with metadata (stream id, frame id, capture timestamp).
- Uses `XADD` with `MAXLEN ~` to cap stream length (bounded buffer).
- Reconnects with exponential backoff and jitter on failure; reports health state.

### 2.2 Detection Workers (Python)

- Run as a Redis consumer group so workers scale horizontally (`XREADGROUP`).
- Model: Ultralytics YOLO (nano or small) via ONNX Runtime.
- Skips stale frames: if frame age exceeds a threshold (for example 300 ms), drop it and increment a counter.
- Publishes detections (class, confidence, normalized bounding box, original timestamps) to the `detections` stream.
- Acknowledges messages with `XACK`; uses `XAUTOCLAIM` to recover work from crashed workers.

### 2.3 Event Processor (Python or Node.js)

- Consumes `detections`, applies simple tracking or dedup (IoU-based or ByteTrack-lite) so one object is not logged 100 times.
- Writes events to PostgreSQL in batches.
- Forwards detections to the rule engine and to the API for live broadcast.

### 2.4 Rule Engine

- Evaluates rules per stream: class filters, zone polygon membership (point-in-polygon), count thresholds, dwell time.
- Emits alerts with a cooldown to prevent alert storms.
- Rules stored in PostgreSQL; cached in memory with change notifications.

### 2.5 API Gateway (FastAPI or Node.js/TypeScript)

- REST for stream management, rules, and event queries.
- WebSocket channels per stream for live detections and system alerts.
- Auth via JWT; request validation with Pydantic or Zod.
- Exposes `/metrics` for Prometheus.

### 2.6 Dashboard (Next.js, TypeScript)

- Stream grid with live frames and a canvas overlay drawn from detection JSON.
- Event timeline with filters; alert panel; stream health indicators.
- Zone drawing tool on a canvas (polygon points saved as normalized coordinates).

### 2.7 Observability

- Prometheus metrics, Grafana dashboards, structured JSON logs.
- Key metrics listed in section 6.

## 3. Technology Choices and Rationale

| Concern | Choice | Why (and alternative) |
| --- | --- | --- |
| Message bus | Redis Streams | Simple, consumer groups, easy to run locally. Kafka is stronger at scale but heavy for a 4-stream demo. |
| Inference runtime | ONNX Runtime | Portable CPU/GPU, sets up phase-two optimization. PyTorch direct is easier but slower. |
| Detection model | YOLO nano/small | Good accuracy-speed balance on CPU. |
| Database | PostgreSQL | Relational queries, time-range filters, indexes. ClickHouse is an option for large volume. |
| API | FastAPI (or Node/TS) | FastAPI shares Pydantic models with Python workers. Node fits your existing stack; pick one and justify. |
| Realtime to browser | WebSocket | Simple, bidirectional. WebRTC only if streaming video itself. |
| Frontend | Next.js + TypeScript | Matches existing skills. |
| Packaging | Docker Compose | One-command start. Kubernetes is an optional extension. |
| Metrics | Prometheus + Grafana | Standard and recognizable to interviewers. |
| Test video | FFmpeg or MediaMTX looping files as RTSP | Reproducible demo without cameras. |

## 4. Data Model

**streams**

- id (uuid), name, source\_url, status, target\_fps, created\_at

**events**

- id (bigserial), stream\_id, ts (timestamptz), class, confidence, bbox (x, y, w, h normalized), track\_id, frame\_id
- Indexes: (stream\_id, ts desc), (class, ts desc)
- Consider monthly partitioning if volume grows.

**rules**

- id, stream\_id, name, class\_filter, zone\_polygon (jsonb), threshold\_count, dwell\_seconds, cooldown\_seconds, enabled

**alerts**

- id, rule\_id, stream\_id, ts, payload (jsonb), delivered (bool)

**users** (if auth is included)

- id, email, password\_hash, role

## 5. API Specification (v1)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | /api/streams | Register a stream |
| GET | /api/streams | List streams with health |
| POST | /api/streams/{id}/start | Start ingestion |
| POST | /api/streams/{id}/stop | Stop ingestion |
| DELETE | /api/streams/{id} | Remove stream |
| GET | /api/events | Query events (stream, class, from, to, cursor, limit) |
| POST | /api/rules | Create rule |
| GET | /api/rules | List rules |
| PATCH | /api/rules/{id} | Update or disable rule |
| GET | /api/alerts | List alerts |
| GET | /api/health | Service health |
| GET | /metrics | Prometheus metrics |
| WS | /ws/streams/{id} | Live frames metadata and detections |
| WS | /ws/alerts | Live alerts |

Use cursor-based pagination for events. Return consistent error shapes with codes.

## 6. Performance and Reliability Design

### Latency budget (target at 10 FPS, per frame)

| Stage | Budget |
| --- | --- |
| Capture and encode | 30 ms |
| Queue wait | 50 ms |
| Inference | 120 ms |
| Post-processing and tracking | 30 ms |
| Delivery to browser | 70 ms |
| **Total** | **about 300 ms** (p95 target under 500 ms) |

Measure each stage by stamping timestamps on the message and computing deltas.

### Backpressure strategy

- Bounded streams with `MAXLEN`.
- Workers drop frames older than the freshness threshold.
- Latest-frame-wins policy for live view; every processed detection still gets stored.
- Export `dropped_frames_total` per stream.

### Failure handling

- Stream disconnect: reconnect with exponential backoff and jitter; status shown in UI.
- Worker crash: pending messages reclaimed via `XAUTOCLAIM` after an idle timeout.
- Redis restart: enable AOF persistence for the detections stream; frames stream is ephemeral.
- Database slowdown: batch writes with a bounded buffer; shed non-critical writes and alert.
- Poison messages: retry limit, then move to a dead-letter stream.

### Scaling

- Add detection workers to scale inference; show throughput vs worker count in the benchmark.
- Identify the first bottleneck (likely inference or JPEG encode) and document the fix.

## 7. Key Metrics (Prometheus)

- `stream_fps{stream}` ingest and processed FPS
- `pipeline_latency_seconds` histogram, labeled by stage
- `frames_dropped_total{stream, reason}`
- `redis_stream_length{stream}` and consumer lag
- `inference_duration_seconds` histogram
- `events_written_total`, `db_write_duration_seconds`
- `stream_status{stream}` (connected, reconnecting, failed)
- `alerts_fired_total{rule}`

## 8. Security

- JWT auth with short expiry; role check for admin endpoints.
- Validate stream URLs (allow-list schemes such as rtsp and file; block internal network targets to prevent SSRF).
- Secrets from environment variables; no credentials in the repository.
- Rate limit the API; sanitize all inputs.
- Do not store raw video by default; if clips are stored, add retention limits.
- Privacy: no face recognition; document intended use.

## 9. Testing Strategy

- **Unit tests:** zone geometry, rule evaluation, tracking and dedup, URL validation.
- **Integration tests:** ingestion to detection to event storage using docker compose and a short sample video.
- **Load tests:** 1, 2, 4, 8 streams; sustained 10 minute runs; report FPS, p50/p95/p99 latency, drop rate, CPU and memory.
- **Chaos tests:** kill a worker, kill Redis, cut a stream; record recovery time.
- **Accuracy sanity check:** run the detector on a small labeled clip and confirm detections are reasonable (the goal is system correctness, not model research).
- **CI:** GitHub Actions running lint, unit tests, and an integration smoke test.

## 10. Deployment

- **Local:** `docker compose up` starting redis, postgres, ingestion, workers, api, dashboard, prometheus, grafana, and a fake RTSP source.
- **Demo:** a single VM (cloud free tier or a small paid instance) with pre-recorded looping streams; or a recorded demo video plus screenshots if hosting inference is too costly.
- **Config:** environment-based, with sensible defaults documented in the README.
- **Optional:** Kubernetes manifests with a KEDA or HPA autoscaling workers on queue length.

## 11. Suggested Repository Structure

```
video-analytics/
  services/
    ingestion/
    worker/
    event-processor/
    api/
  web/                # Next.js dashboard
  infra/
    docker-compose.yml
    prometheus/
    grafana/
  benchmarks/         # load test scripts and results
  docs/
    architecture.md
    design-decisions.md
  README.md
```

## 12. Phase Two: Optimization

- Export the model to ONNX, then TensorRT or OpenVINO.
- Add dynamic batching across streams in the worker.
- Try INT8 or FP16 quantization and measure accuracy impact.
- Publish a before/after table: latency, throughput, accuracy, resource use.
- Target bullet: "Cut per-frame inference latency by X% and raised streams per machine from A to B with under 1% accuracy loss."

## 13. Definition of Done

- All Must requirements implemented and demoed.
- Load test results and chaos test results documented with real numbers.
- One-command startup works on a clean machine.
- README with architecture diagram, setup steps, benchmark table, and a design-decisions section explaining each major trade-off.
- Live demo link or demo video.
- Resume bullets written from measured results only.

## 14. Resume Bullet Templates (fill in with real numbers)

- Built a real-time video analytics platform processing N concurrent camera streams at F FPS with p95 end-to-end latency of X ms, using Python, ONNX Runtime, Redis Streams, FastAPI, and Next.js.
- Designed backpressure and frame-dropping policy that kept latency under X ms at 2x load, with a Y% drop rate and automatic recovery from stream and worker failures within Z seconds.
- Instrumented the pipeline with Prometheus and Grafana, identified the inference stage as the bottleneck, and raised throughput by X% through batching and quantization.
- Containerized the full stack with Docker Compose and added CI with integration and load tests.
