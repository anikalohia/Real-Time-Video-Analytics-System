# Project Status Audit

**Audit date:** 2026-10-31

**Repository:** `video-analytics/` (plus uncommitted local work)

**Source of truth:** `PRD and TRD Real-Time Video Analytics Platform.md` (repo root)

## Environment detected

| Item | Value | How measured |
| --- | --- | --- |
| CPU | 12th Gen Intel Core i5-1235U, 10 physical / 12 logical cores | `Get-CimInstance Win32_Processor` |
| RAM | 7.73 GB | `Get-CimInstance Win32_OperatingSystem` |
| GPU | Intel UHD Graphics (no CUDA) | `Get-CimInstance Win32_VideoController` |
| OS | Windows (win32), PowerShell 5.1 | environment |
| Python | 3.12.4 (project targets 3.11) | `python --version` |
| Node / npm | v22.19.0 / 10.9.3 | `node --version`, `npm --version` |
| Docker CLI / Compose | 29.9.2 / v5.6.1 | `docker --version`, `docker compose version` |
| Docker daemon | **available** (Docker Desktop, WSL2 Ubuntu running) | `docker info` |
| Docker build path | **non-OneDrive copy works**; original OneDrive checkout fails with `invalid file request` for cloud-reparse files | `docker compose up --build` from both paths |
| Global ONNX Runtime | **import crashes** with Windows access violation (`0xC0000005`); global 1.31.0 | `python -c "import onnxruntime"` |
| Pinned ONNX Runtime | **works**: 1.20.1 in an isolated venv | `onnxruntime.__version__` |

The full Compose stack builds and runs from a copy outside OneDrive. The
original OneDrive path cannot be used as a Docker build context because
OneDrive placeholder files are reparse points; Docker BuildKit rejects them
with `ERROR: invalid file request ...`. Runtime checks below were measured from
the non-OneDrive copy of the same source.

## Commands actually run

| Command | Result |
| --- | --- |
| `python -m pytest -q` | **44 passed** (units/integration using fakeredis + SQLite) |
| `python -m ruff check services scripts benchmarks` | **Passed** |
| `python -m ruff format --check services scripts benchmarks` | **Passed** |
| `cd web && npm run typecheck` | **Passed** |
| `docker compose -f docker-compose.yml config` | **Valid** |
| `docker compose up --build` | **Passed** from a non-OneDrive copy; all long-running services healthy |
| `bash -n scripts/smoke.sh` | **Passed** (Git Bash 5.2.26 syntax check; Windows `py -3` fallback added) |
| `docker manifest inspect` for critical images | **Found**: mediaMTX, ffmpeg, Prometheus, Grafana, Redis, Postgres tags |
| `scripts/smoke.sh` | **PASS**: API health, dashboard, demo stream, 98,271-byte frame, 5 events, 5 alerts |
| `GET /api/health`, `/api/streams`, frame, events, alerts | **200/OK** against the running Compose stack |
| Auth login / unauthenticated mutation | **Passed**: admin login returns JWT; unauthenticated stream creation returns 401 |
| Prometheus targets | **All up**: api, event-processor, ingestion, worker, prometheus |
| Web / Prometheus / Grafana HTTP checks | **200** on ports 3000, 9090, 3001 |
| `scripts/local_pipeline.py --backend mock --seconds 6` | **Passed**: 30 frames, 46 events, latest frame cached |
| `scripts/local_pipeline.py --backend onnx --seconds 12` | **Passed**: 61 frames, 18 events on CPU, ONNX Runtime 1.20.1 |
| Real ONNX frame sanity check | **5 detections** on `vtest.avi` (3 people, 1 car, 1 truck) |
| `scripts/fetch_sample.py samples/sample.avi` | Downloaded `vtest.avi` (8,131,690 bytes) |
| Manual auth/rate-limit check (`AUTH_ENABLED=1`) | **Passed**: unauth mutation blocked, login works, 3rd login returns 429 |
| `cd web && npm run build` | **Passed** on retry (4 static routes generated) |
| Browser/Grafana rendering (2026-10-31) | **Passed**: live frame, canvas overlays, event feed, alert panel, Grafana panels |
| `benchmarks/load_test.py` in Compose network (2026-10-31) | **Completed**: 2-stream and 4-stream runs; NFR not met (see below) |

## Requirement status

Status values: **done**, **partial**, **missing**, **broken**, **not measured**,
**not met**.

### Functional requirements

| ID | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| F1 | Register/start/stop/delete streams via API and UI | done | API CRUD/start/stop/delete; dashboard controls in `StreamGrid.tsx`; delete cascades |
| F2 | Ingest RTSP and looped files | done | `StreamIngestor` supports RTSP/files; MediaMTX + fake camera in Compose; loop/reconnect behavior |
| F3 | Object detection on sampled frames, publish detections | done | ONNX v5/v8, FP16/FP32 input support; real 5-detection check; mock backend; worker tests |
| F4 | Persist events (ts, stream, class, confidence, bbox) | done | `Event`/`Alert` models, Alembic migration, indexes, batch commit |
| F5 | Live dashboard with overlay + event feed | done | Latest-frame endpoint + JPEG polling, canvas overlays, event filters/pagination over REST, alert WebSocket |
| F6 | Zone/count rule engine | done | IoU tracking, unique-object count, dwell state, zones, cooldown; zone editor UI |
| F7 | Alerts in UI and webhook | done | `WebhookDispatcher` with retries/backoff, delivery status, alert panel |
| F8 | Event query filters + pagination | done | Cursor envelopes for events and alerts, `from_ts`/`to_ts`, stream/class filters, indexes |
| F9 | Metrics endpoint + Grafana dashboards | done | `ep_*`/`api_*` metrics, Prometheus targets all up at runtime, Grafana panels rendered with live data on 2026-10-31 |
| F10 | Reconnect with backoff | done | Exponential backoff + jitter, file-source health update, health exposed in API/UI; live RTSP reconnect unverified |
| F11 | Event clips/snapshots (Could) | missing | Deferred; not required for Must/Should acceptance |
| F12 | Auth | done | Auth enabled by default for mutations, 15-minute JWT, login UI, rate limiting, env secrets |

### Non-functional requirements

| Requirement | Status | Evidence |
| --- | --- | --- |
| p95 end-to-end < 500 ms | not met | p95 806.1 ms on the 4-stream overload run; 710.9 ms on 2 streams at 3 FPS (CPU-only) |
| 4 streams at 10 FPS | not met | Generator reached only ~15 FPS aggregate; 82.2% stale/dropped on 1 worker |
| Recovery < 30 s | not measured | XAUTOCLAIM/backoff implemented; no chaos measurement |
| Backpressure / drop stale frames | done | Stale ACK/drop, bounded streams/buffer, latest-frame-wins; drop reasons/metrics; observed under overload |
| Observability: Prometheus + structured logs | done | Service metrics, stage/lag gauges, JSON logs, provisioned dashboard; runtime scrape and panel rendering verified |
| Portability: one command | partial | Compose smoke passes from a non-OneDrive path; original OneDrive checkout still fails as a Docker build context |
| Security: env secrets, URL validation, auth | partial | URL validation, auth, rate limit, CORS; dev-default JWT/admin values exist and frontend token expiry is not handled |
| DB migrations | done | Alembic initial migration, indexes, migrate job before seed/services |

## Remaining verification gaps

1. **Capacity/chaos**: p95 and drop rates are measured, but the 4-stream/10 FPS
   NFR is not met on CPU. Recovery <30 s still needs a chaos test.
2. **Real RTSP**: only the Compose MediaMTX/fake-camera path and local files are
   configured; a physical camera is untested.
3. **GPU**: unavailable; all reported inference is CPU-only.
4. **Browser resilience**: dashboard WebSocket clients do not auto-reconnect
   after an API restart; a page refresh is required.

## Honest limitations

- Docker Desktop/WSL2 is now available, but the original OneDrive checkout
  cannot be used as a Docker build context. Move/copy the repository outside
  OneDrive before running Compose; the verified run used such a copy.
- Global ONNX Runtime 1.31.0 crashes on this Windows install; the project pins
  1.20.1 and was verified in an isolated venv. The container worker uses ONNX
  successfully.
- No GPU; there is no TensorRT/OpenVINO path in this phase.
- The local functional pipeline uses fakeredis + SQLite; the Compose smoke uses
  real Redis/PostgreSQL. Load results are in `benchmarks/results/`.
- Processing is at-least-once; a post-commit ACK failure can duplicate events.
- Dev-default JWT/admin credentials are present for the demo; change them before
  exposing the stack.
- The API required a `bcrypt==4.0.1` pin: bcrypt 5.x is incompatible with
  passlib 1.7.4 and caused admin seeding to fail.
- The fake-camera H.264 source logs transient decode warnings during stream
  startup; ingestion still recovers, caches frames, and produces events.
