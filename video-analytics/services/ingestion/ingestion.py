import base64
import json
import random
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import cv2
import numpy as np
import redis
from ingest_config import get_config

try:
    from prometheus_client import Counter, Gauge, start_http_server
except ImportError:  # pragma: no cover
    Counter = Gauge = None
    start_http_server = None


cfg = get_config()

if Counter:
    frames_ingested = Counter('frames_ingested_total', 'Frames ingested', ['stream'])
    frames_published = Counter('frames_published_total', 'Frames published', ['stream'])
    reconnect_attempts = Counter('reconnect_attempts_total', 'Reconnect attempts', ['stream'])
    stream_status = Gauge(
        'stream_status',
        'Stream status (1=connected,2=reconnecting,3=failed)',
        ['stream'],
    )
    ingest_fps = Gauge(
        'ingestion_stream_fps', 'Ingested frames per second', ['stream', 'direction']
    )
else:  # pragma: no cover
    frames_ingested = frames_published = reconnect_attempts = stream_status = ingest_fps = None


def log_event(**fields: Any) -> None:
    print(json.dumps({'service': 'ingestion', **fields}, default=str), flush=True)


def _is_file_source(source_url: str) -> bool:
    if '://' not in source_url:
        return True
    return urlparse(source_url).scheme == 'file'


class StreamIngestor:
    def __init__(
        self,
        stream_id: str,
        source_url: str,
        target_fps: int | None = None,
        status_cb: Callable[[str], None] | None = None,
    ):
        self.stream_id = stream_id
        self.source_url = source_url
        self.target_fps = target_fps or cfg.max_fps
        self.status_cb = status_cb
        self.redis: redis.Redis | None = None
        self.cap: cv2.VideoCapture | None = None
        self.running = False
        self.frame_id = 0
        self.is_file = _is_file_source(source_url)
        self._frames_since_fps = 0
        self._fps_window_start = time.monotonic()

    def _set_health(self, health: str) -> None:
        if stream_status:
            value = {'connected': 1, 'reconnecting': 2, 'failed': 3}.get(health, 0)
            stream_status.labels(stream=self.stream_id).set(value)
        if self.status_cb:
            try:
                self.status_cb(health)
            except Exception:
                pass
        log_event(event='stream_health', stream_id=self.stream_id, health=health)

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

    def open_stream(self):
        if self.is_file and self.cap is not None:
            self.cap.release()
        self.cap = cv2.VideoCapture(self.source_url)
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        if not self.cap.isOpened():
            self.cap = None
            raise RuntimeError(f'Failed to open stream {self.source_url}')

    def publish_frame(self, frame: np.ndarray, capture_ts: float):
        self.connect_redis()
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
        ret, buf = cv2.imencode('.jpg', frame, encode_param)
        if not ret:
            return
        jpg_bytes = buf.tobytes()
        publish_ts = time.time()
        msg: dict[str, Any] = {
            'stream_id': self.stream_id,
            'frame_id': self.frame_id,
            'ts': publish_ts,
            'publish_ts': publish_ts,
            'capture_ts': capture_ts,
            'width': int(frame.shape[1]),
            'height': int(frame.shape[0]),
            'format': 'jpeg',
        }
        payload = {
            'metadata': json.dumps(msg),
            'image_b64': base64.b64encode(jpg_bytes).decode('utf-8'),
        }
        stream_name = f'frames:{self.stream_id}'
        pipe = self.redis.pipeline(transaction=False)
        pipe.xadd(stream_name, payload, maxlen=cfg.max_stream_len, approximate=True)
        pipe.hset(
            f'latest:{self.stream_id}',
            mapping={
                'image_b64': payload['image_b64'],
                'ts': str(publish_ts),
                'width': str(msg['width']),
                'height': str(msg['height']),
            },
        )
        pipe.expire(f'latest:{self.stream_id}', cfg.latest_frame_ttl)
        pipe.execute()
        self.frame_id += 1
        if frames_published:
            frames_published.labels(stream=self.stream_id).inc()
        if ingest_fps:
            self._frames_since_fps += 1
            elapsed = time.monotonic() - self._fps_window_start
            if elapsed >= 1.0:
                ingest_fps.labels(stream=self.stream_id, direction='ingest').set(
                    self._frames_since_fps / elapsed
                )
                self._frames_since_fps = 0
                self._fps_window_start = time.monotonic()

    def run(self):
        self.running = True
        delay = cfg.reconnect_base_delay
        failures = 0
        next_frame = time.monotonic()
        while self.running:
            try:
                if self.cap is None or not self.cap.isOpened():
                    self.open_stream()
                    self._set_health('connected')

                ret, frame = self.cap.read()
                if not ret:
                    if self.is_file:
                        # Rewind a file source so the demo loops, but do not
                        # treat a normal EOF as a failure.
                        self.cap.release()
                        self.cap = None
                        time.sleep(min(0.05, 1.0 / max(1, self.target_fps)))
                        continue
                    raise RuntimeError('Stream ended or read failed')

                capture_ts = time.time()
                if frames_ingested:
                    frames_ingested.labels(stream=self.stream_id).inc()
                self.publish_frame(frame, capture_ts)
                delay = cfg.reconnect_base_delay
                failures = 0

                next_frame += 1.0 / max(1, self.target_fps)
                sleep_for = next_frame - time.monotonic()
                if sleep_for > 0:
                    time.sleep(sleep_for)
                else:
                    # We are behind; do not accumulate a latency debt.
                    next_frame = time.monotonic()
            except Exception as exc:
                failures += 1
                health = 'reconnecting' if failures < 5 else 'failed'
                self._set_health(health)
                if reconnect_attempts:
                    reconnect_attempts.labels(stream=self.stream_id).inc()
                log_event(
                    event='reconnect',
                    stream_id=self.stream_id,
                    attempt=failures,
                    error=str(exc),
                    delay_s=round(delay, 2),
                )
                if self.is_file:
                    # Files usually fail only if missing/corrupt; still retry.
                    time.sleep(min(delay, cfg.reconnect_max_delay))
                else:
                    jitter = random.uniform(0, min(1.0, delay * 0.25))
                    time.sleep(min(delay + jitter, cfg.reconnect_max_delay))
                delay = min(delay * 2, cfg.reconnect_max_delay)
                if self.cap:
                    self.cap.release()
                    self.cap = None

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()
            self.cap = None
        self._set_health('stopped')


def start_metrics():
    if start_http_server and Counter:
        try:
            start_http_server(cfg.metrics_port)
        except Exception:
            pass
