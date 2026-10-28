import base64
import json
import os
import socket
import time

import cv2
import numpy as np
import redis
from worker_config import get_config


def build_detector(backend: str, **kwargs):
    if backend == 'mock':
        from mock_detector import MockDetector

        return MockDetector(**kwargs)
    if backend == 'yolo':
        from yolo_torch import YOLOTorchDetector

        return YOLOTorchDetector(**kwargs)
    from onnx_model import YOLOv5ONNX

    return YOLOv5ONNX(**kwargs)


try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
except ImportError:  # pragma: no cover
    Counter = Histogram = Gauge = None
    start_http_server = None


cfg = get_config()

if Histogram:
    inference_duration = Histogram('inference_duration_seconds', 'Inference duration', ['backend'])
    postprocess_duration = Histogram('postprocess_duration_seconds', 'Postprocess duration')
    pipeline_latency = Histogram(
        'pipeline_latency_seconds',
        'Per-stage pipeline latency',
        ['stage'],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )
else:  # pragma: no cover
    inference_duration = postprocess_duration = pipeline_latency = None

if Counter:
    frames_processed = Counter('frames_processed_total', 'Frames processed', ['stream'])
    frames_dropped = Counter('frames_dropped_total', 'Frames dropped', ['stream', 'reason'])
    detections_published = Counter('detections_published_total', 'Detections published')
    dead_lettered = Counter(
        'messages_dead_lettered_total', 'Messages moved to the dead-letter stream', ['reason']
    )
else:  # pragma: no cover
    frames_processed = frames_dropped = detections_published = dead_lettered = None

if Gauge:
    stream_fps = Gauge('stream_fps', 'Processed frames per second', ['stream', 'direction'])
    redis_stream_length = Gauge('redis_stream_length', 'Redis stream length', ['stream'])
    worker_lag = Gauge('redis_consumer_lag', 'Approximate consumer group lag', ['stream', 'group'])
else:  # pragma: no cover
    stream_fps = redis_stream_length = worker_lag = None


def log_event(**fields):
    print(json.dumps({'service': 'worker', **fields}, default=str), flush=True)


class DetectionWorker:
    def __init__(self):
        self.redis: redis.Redis | None = None
        self.consumer_name = cfg.consumer_name or f'worker-{socket.gethostname()}-{os.getpid()}'
        self.detector = build_detector(
            cfg.detector_backend,
            model_path=cfg.model_path,
            model_url=cfg.model_url,
            input_size=cfg.input_size,
            conf_threshold=cfg.confidence_threshold,
            nms_threshold=cfg.nms_threshold,
        )
        self.running = True
        self._fps_counts: dict[str, int] = {}
        self._fps_start = time.monotonic()

    def connect_redis(self):
        if self.redis:
            try:
                self.redis.ping()
                return
            except Exception:
                self.redis = None
        self.redis = redis.Redis(
            host=cfg.redis_host,
            port=cfg.redis_port,
            db=cfg.redis_db,
            decode_responses=True,
        )
        self.redis.ping()

    def ensure_consumer_group(self, stream_name: str):
        self.connect_redis()
        try:
            self.redis.xgroup_create(stream_name, cfg.consumer_group, id='0', mkstream=True)
        except redis.ResponseError as exc:
            if 'BUSYGROUP' not in str(exc):
                raise

    def decode_frame(self, image_b64: str) -> np.ndarray:
        jpg_bytes = base64.b64decode(image_b64)
        nparr = np.frombuffer(jpg_bytes, np.uint8)
        return cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    def normalize_box(self, x1, y1, x2, y2, w, h):
        nx1 = x1 / w if w > 0 else 0
        ny1 = y1 / h if h > 0 else 0
        nx2 = x2 / w if w > 0 else 0
        ny2 = y2 / h if h > 0 else 0
        return {
            'x': float(max(0.0, min(1.0, nx1))),
            'y': float(max(0.0, min(1.0, ny1))),
            'w': float(max(0.0, min(1.0, nx2 - nx1))),
            'h': float(max(0.0, min(1.0, ny2 - ny1))),
        }

    def _drop(self, stream_id: str, reason: str):
        if frames_dropped:
            frames_dropped.labels(stream=stream_id or 'unknown', reason=reason).inc()

    def _retry_count(self, stream_name: str, msg_id: str) -> int:
        key = f'retry:{stream_name}'
        attempts = int(self.redis.hincrby(key, msg_id, 1))
        self.redis.expire(key, 3600)
        return attempts

    def _clear_retry(self, stream_name: str, msg_id: str):
        self.redis.hdel(f'retry:{stream_name}', msg_id)

    def _dead_letter(self, stream_name: str, msg_id: str, reason: str, meta: dict):
        try:
            self.redis.xadd(
                cfg.dead_letter_stream,
                {
                    'source_stream': stream_name,
                    'source_id': msg_id,
                    'reason': reason,
                    'metadata': json.dumps(meta, default=str),
                },
                maxlen=10000,
                approximate=True,
            )
            if dead_lettered:
                dead_lettered.labels(reason=reason).inc()
            self.redis.xack(stream_name, cfg.consumer_group, msg_id)
            self._clear_retry(stream_name, msg_id)
            log_event(
                event='dead_letter',
                stream_id=meta.get('stream_id'),
                frame_id=meta.get('frame_id'),
                msg_id=msg_id,
                reason=reason,
            )
        except Exception as exc:
            log_event(event='dead_letter_failed', msg_id=msg_id, error=str(exc))

    def _handle_failure(
        self, stream_name: str, msg_id: str, reason: str, meta: dict, exc: Exception
    ):
        self._drop(str(meta.get('stream_id', 'unknown')), reason)
        attempts = self._retry_count(stream_name, msg_id)
        log_event(
            event='frame_failed',
            stream_id=meta.get('stream_id'),
            frame_id=meta.get('frame_id'),
            msg_id=msg_id,
            reason=reason,
            attempt=attempts,
            error=str(exc),
        )
        if attempts >= cfg.max_delivery_attempts:
            self._dead_letter(stream_name, msg_id, reason, meta)

    def process_message(self, stream_name: str, msg_id: str, fields: dict[str, str]):
        meta: dict = {}
        stream_id = 'unknown'
        try:
            meta = json.loads(fields.get('metadata', '{}'))
            stream_id = str(meta.get('stream_id', 'unknown'))
            image_b64 = fields.get('image_b64', '')
            if not image_b64:
                raise ValueError('missing image payload')

            now = time.time()
            capture_ts = float(meta.get('capture_ts', meta.get('ts', now)))
            publish_ts = float(meta.get('publish_ts', meta.get('ts', capture_ts)))
            age_ms = (now - capture_ts) * 1000
            if age_ms > cfg.stale_threshold_ms:
                # A stale frame is intentionally discarded; ack it so it does
                # not sit in the PEL forever.
                self._drop(stream_id, 'stale')
                self.redis.xack(stream_name, cfg.consumer_group, msg_id)
                self._clear_retry(stream_name, msg_id)
                if pipeline_latency:
                    pipeline_latency.labels(stage='queue_wait').observe(
                        max(0.0, publish_ts - capture_ts)
                    )
                return

            if pipeline_latency:
                pipeline_latency.labels(stage='queue_wait').observe(max(0.0, now - publish_ts))

            decoded = self.decode_frame(image_b64)
            if decoded is None or decoded.size == 0:
                raise ValueError('jpeg decode returned an empty frame')
            h, w = decoded.shape[:2]

            inference_start = time.time()
            dets = self.detector.detect(decoded)
            inference_elapsed = time.time() - inference_start
            if inference_duration:
                inference_duration.labels(backend=cfg.detector_backend).observe(inference_elapsed)
            if pipeline_latency:
                pipeline_latency.labels(stage='inference').observe(inference_elapsed)

            post_start = time.time()
            detection_ts = time.time()
            det_msgs = []
            for cls_id, conf, x1, y1, x2, y2 in dets:
                box = self.normalize_box(x1, y1, x2, y2, w, h)
                det_msgs.append(
                    {
                        'stream_id': stream_id,
                        'frame_id': meta.get('frame_id'),
                        'ts': detection_ts,
                        'capture_ts': capture_ts,
                        'publish_ts': publish_ts,
                        'width': w,
                        'height': h,
                        'class_id': int(cls_id),
                        'class': self.detector.class_names[int(cls_id)]
                        if int(cls_id) < len(self.detector.class_names)
                        else str(cls_id),
                        'confidence': float(conf),
                        'bbox': box,
                        'inference_ms': round(inference_elapsed * 1000, 3),
                    }
                )
            post_elapsed = time.time() - post_start
            if postprocess_duration:
                postprocess_duration.observe(post_elapsed)
            if pipeline_latency:
                pipeline_latency.labels(stage='postprocess').observe(post_elapsed)

            if det_msgs:
                self.redis.xadd(
                    'detections',
                    {'detections': json.dumps(det_msgs)},
                    maxlen=10000,
                    approximate=True,
                )
                if detections_published:
                    detections_published.inc(len(det_msgs))
            if frames_processed:
                frames_processed.labels(stream=stream_id).inc()
            self._count_fps(stream_id)
            self.redis.xack(stream_name, cfg.consumer_group, msg_id)
            self._clear_retry(stream_name, msg_id)
        except Exception as exc:
            self._handle_failure(stream_name, msg_id, 'processing_error', meta, exc)

    def _count_fps(self, stream_id: str):
        self._fps_counts[stream_id] = self._fps_counts.get(stream_id, 0) + 1
        elapsed = time.monotonic() - self._fps_start
        if elapsed >= 1.0:
            if stream_fps:
                for sid, count in self._fps_counts.items():
                    stream_fps.labels(stream=sid, direction='processed').set(count / elapsed)
            self._fps_counts.clear()
            self._fps_start = time.monotonic()

    def discover_streams(self) -> list[str]:
        self.connect_redis()
        found = []
        for key in self.redis.scan_iter(match='frames:*', count=100):
            found.append(key)
            self.ensure_consumer_group(key)
        return found

    def refresh_stream_metrics(self, streams_to_read: list[str]):
        for stream_name in streams_to_read:
            try:
                if redis_stream_length:
                    redis_stream_length.labels(stream=stream_name).set(self.redis.xlen(stream_name))
                if worker_lag:
                    groups = self.redis.xinfo_groups(stream_name)
                    for group in groups:
                        if group.get('name') == cfg.consumer_group:
                            lag = group.get('lag')
                            if lag is None:
                                lag = group.get('pending', 0)
                            worker_lag.labels(stream=stream_name, group=cfg.consumer_group).set(lag)
            except Exception:
                pass

    def reclaim_stale(self, streams_to_read: list[str]):
        """Reclaim pending messages from crashed consumers after idle timeout."""
        for stream_name in streams_to_read:
            try:
                resp = self.redis.xautoclaim(
                    stream_name,
                    cfg.consumer_group,
                    self.consumer_name,
                    min_idle_time=cfg.reclaim_min_idle_ms,
                    start_id='0-0',
                    count=10,
                )
                if not resp or len(resp) < 2 or not resp[1]:
                    continue
                for msg_id, fields in resp[1]:
                    self.process_message(stream_name, msg_id, fields)
            except Exception:
                pass

    def run(self):
        self.connect_redis()
        log_event(
            event='worker_started',
            backend=cfg.detector_backend,
            consumer=self.consumer_name,
        )
        streams_to_read: list[str] = []
        last_discovery = 0.0
        last_reclaim = 0.0
        last_metrics = 0.0
        while self.running:
            try:
                now = time.time()
                if now - last_discovery > 5:
                    streams_to_read = self.discover_streams()
                    last_discovery = now
                if now - last_reclaim > 30:
                    self.reclaim_stale(streams_to_read)
                    last_reclaim = now
                if now - last_metrics > 5:
                    self.refresh_stream_metrics(streams_to_read)
                    last_metrics = now
                if not streams_to_read:
                    time.sleep(1)
                    continue

                streams = {s: '>' for s in streams_to_read}
                res = self.redis.xreadgroup(
                    cfg.consumer_group,
                    self.consumer_name,
                    streams,
                    count=10,
                    block=2000,
                )
                if not res:
                    continue
                for stream_name, messages in res:
                    for msg_id, fields in messages:
                        self.process_message(stream_name, msg_id, fields)
            except Exception as exc:
                log_event(event='worker_loop_error', error=str(exc))
                time.sleep(1)


def start_metrics():
    if start_http_server:
        try:
            start_http_server(cfg.metrics_port)
        except Exception:
            pass
