import base64
import json
import random
import time
from typing import Optional, Dict, Any

import cv2
import numpy as np
import redis

from ingest_config import get_config

try:
    from prometheus_client import Counter, Gauge, start_http_server
except ImportError:
    Counter = Gauge = None
    start_http_server = None


cfg = get_config()

# Metrics
if Counter:
    frames_ingested = Counter("frames_ingested_total", "Frames ingested", ["stream"])
    frames_published = Counter("frames_published_total", "Frames published", ["stream"])
    reconnect_attempts = Counter("reconnect_attempts_total", "Reconnect attempts", ["stream"])
    stream_status = Gauge("stream_status", "Stream status (1=connected,2=reconnecting,3=failed)", ["stream"])
else:
    frames_ingested = frames_published = reconnect_attempts = stream_status = None


class StreamIngestor:
    def __init__(self, stream_id: str, source_url: str):
        self.stream_id = stream_id
        self.source_url = source_url
        self.redis: Optional[redis.Redis] = None
        self.cap: Optional[cv2.VideoCapture] = None
        self.running = False
        self.frame_id = 0
        self.last_frame_ts = 0.0

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
        self.cap = cv2.VideoCapture(self.source_url)
        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open stream {self.source_url}")

    def publish_frame(self, frame: np.ndarray):
        self.connect_redis()
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
        ret, buf = cv2.imencode(".jpg", frame, encode_param)
        if not ret:
            return
        jpg_bytes = buf.tobytes()
        ts = time.time()
        msg: Dict[str, Any] = {
            "stream_id": self.stream_id,
            "frame_id": self.frame_id,
            "ts": ts,
            "capture_ts": self.last_frame_ts if self.last_frame_ts else ts,
            "width": frame.shape[1],
            "height": frame.shape[0],
            "format": "jpeg",
        }
        # The frame is transported as base64 so we can use a single decoded
        # Redis connection for both metadata and payload.
        payload = {
            "metadata": json.dumps(msg),
            "image_b64": base64.b64encode(jpg_bytes).decode("utf-8"),
        }
        stream_name = f"frames:{self.stream_id}"
        self.redis.xadd(
            stream_name,
            payload,
            maxlen=cfg.max_stream_len,
            approximate=True,
        )
        self.frame_id += 1
        if frames_published:
            frames_published.labels(stream=self.stream_id).inc()

    def run(self):
        self.running = True
        if stream_status:
            stream_status.labels(stream=self.stream_id).set(1)
        delay = cfg.reconnect_base_delay
        target_fps = getattr(self, "target_fps", cfg.max_fps) or cfg.max_fps
        while self.running:
            try:
                if self.cap is None or not self.cap.isOpened():
                    self.open_stream()
                    delay = cfg.reconnect_base_delay
                ret, frame = self.cap.read()
                if not ret:
                    raise RuntimeError("Stream ended or read failed")
                if frames_ingested:
                    frames_ingested.labels(stream=self.stream_id).inc()
                self.last_frame_ts = time.time()
                self.publish_frame(frame)
                # simple FPS pacing
                time.sleep(1.0 / target_fps)
            except Exception as e:
                if stream_status:
                    stream_status.labels(stream=self.stream_id).set(3)
                if reconnect_attempts:
                    reconnect_attempts.labels(stream=self.stream_id).inc()
                time.sleep(min(delay, cfg.reconnect_max_delay))
                delay *= 2
                delay += random.uniform(0, 0.1)
                if self.cap:
                    self.cap.release()
                    self.cap = None


def start_metrics():
    if start_http_server and Counter:
        try:
            start_http_server(8001)
        except Exception:
            pass
