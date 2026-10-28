# Design Decisions

## Redis Streams instead of Kafka

The demo target is a handful of streams on one machine. Redis Streams gives
consumer groups, pending-entry lists, `XAUTOCLAIM`, and bounded streams with
`MAXLEN` without operating a broker cluster. Kafka would be the right choice
for sustained multi-node scale, but it adds operational weight here.

## Bounded queues and latest-frame cache

Frames are worth less as they age. The pipeline:

- caps Redis streams with `MAXLEN`;
- drops frames older than `STALE_THRESHOLD_MS` before inference;
- overwrites `latest:{stream_id}` for the dashboard;
- caps the event-processor DB buffer.

This converts overload into measured frame drops instead of unbounded latency
and memory growth. The event processor deliberately drops when its buffer is
full; silently accumulating events would eventually OOM the service.

## ACK after commit

Consumers ACK only after successful publication/commit. A failed DB write
leaves detections pending in the consumer group so they can be reclaimed and
retried; the buffer is bounded, so a prolonged outage drops the oldest buffered
events rather than growing memory indefinitely. Malformed detection payloads
are retried and then moved to `dead-letter` with the reason and original
metadata. Database write failures are not currently dead-lettered. The result
is at-least-once delivery: a process crash after commit but before ACK can
duplicate an event.

## IoU tracking and dedup

A full multi-object tracker (Kalman + Hungarian assignment) is unnecessary for
the demo. A class-aware greedy IoU tracker with a short TTL stops the same
object being logged on every frame. Events carry `track_id`, so rules count
unique objects rather than raw detection boxes.

## Client-side overlays

The API serves the latest JPEG plus detection JSON. The browser draws boxes on
a canvas. This keeps the server from re-encoding annotated video and lets the
UI choose its own render rate.

## ONNX Runtime

ONNX Runtime provides a portable CPU path and a clear route to GPU/TensorRT or
OpenVINO later. The loader supports YOLOv5 and YOLOv8 output layouts and both
FP16 and FP32 input models, because the published YOLOv5 ONNX artifact expects
FP16 on some releases.

## PostgreSQL

Events and alerts are relational, filtered by stream/class/time, and queried
with cursor pagination. PostgreSQL indexes fit those access patterns and the
schema is managed by Alembic. SQLite is used only in tests/local smoke runs.

## FastAPI + Next.js

FastAPI gives typed request validation, async WebSockets, and simple Prometheus
integration. Next.js provides the dashboard and polygon editor without a
separate frontend build system.

## Authentication and SSRF protection

The dashboard is meant to be opened immediately, so GET routes are public and
mutations require an admin JWT. Stream sources are untrusted input: schemes and
file extensions are allow-listed and DNS-resolved private/loopback addresses
are blocked. The Compose demo explicitly allow-lists `mediamtx`; this is not a
default for public deployments.

## One-command demo

The root `docker-compose.yml` includes `infra/docker-compose.yml` so
`docker compose up --build` works from the repository root. Migrations and
demo seeding run as one-shot services with `service_completed_successfully`
dependencies. Seeding is idempotent and never overwrites a user's stopped
stream.

## Not decided by convenience

- No face recognition or biometric features; the project stays within the TRD.
- No fabricated benchmark numbers. Docker/ONNX-runtime verification is reported
  honestly in `docs/STATUS.md`, including what could not be measured.
