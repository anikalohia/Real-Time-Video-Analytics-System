import base64
import json
import time
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
import redis

from worker_config import get_config


def build_detector(backend: str, **kwargs):
    if backend == "mock":
        from mock_detector import MockDetector
        return MockDetector(**kwargs)
    if backend == "yolo":
        from yolo_torch import YOLOTorchDetector
        return YOLOTorchDetector(**kwargs)
    from onnx_model import YOLOv5ONNX
    return YOLOv5ONNX(**kwargs)

try:
    from prometheus_client import Counter, Histogram, Gauge, start_http_server
except ImportError:
    Counter = Histogram = Gauge = None
    start_http_server = None


cfg = get_config()

# Metrics
if Histogram:
    inference_duration = Histogram("inference_duration_seconds", "Inference duration")
    postprocess_duration = Histogram("postprocess_duration_seconds", "Postprocess duration")
else:
    inference_duration = postprocess_duration = None
if Counter:
    frames_processed = Counter("frames_processed_total", "Frames processed", ["stream"])
    frames_dropped = Counter("frames_dropped_total", "Frames dropped", ["stream", "reason"])
    detections_published = Counter("detections_published_total", "Detections published")
else:
    frames_processed = frames_dropped = detections_published = None


class DetectionWorker:
    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self.detector = build_detector(
            cfg.detector_backend,
            model_path=cfg.model_path,
            input_size=cfg.input_size,
            conf_threshold=cfg.confidence_threshold,
            nms_threshold=cfg.nms_threshold,
        )
        self.running = True

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
            self.redis.xgroup_create(stream_name, cfg.consumer_group, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def decode_frame(self, image_b64: str) -> np.ndarray:
        jpg_bytes = base64.b64decode(image_b64)
        nparr = np.frombuffer(jpg_bytes, np.uint8)
        return cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    def normalize_box(self, x1, y1, x2, y2, w, h):
        # already in pixels; normalize
        nx1 = x1 / w if w > 0 else 0
        ny1 = y1 / h if h > 0 else 0
        nx2 = x2 / w if w > 0 else 0
        ny2 = y2 / h if h > 0 else 0
        bw = nx2 - nx1
        bh = ny2 - ny1
        return {"x": float(nx1), "y": float(ny1), "w": float(bw), "h": float(bh)}

    def process_message(self, stream_name: str, msg_id: str, fields: Dict[str, str]):
        try:
            meta = json.loads(fields.get("metadata", "{}"))
            image_b64 = fields.get("image_b64", "")
            if not image_b64:
                return
            ts_now = time.time()
            cap_ts = meta.get("capture_ts", ts_now)
            age_ms = (ts_now - cap_ts) * 1000
            if age_ms > cfg.stale_threshold_ms:
                if frames_dropped:
                    frames_dropped.labels(stream=meta.get("stream_id", "unknown"), reason="stale").inc()
                return
            frame = self.decode_frame(image_b64)
            h, w = frame.shape[:2]
            start = time.time()
            dets = self.detector.detect(frame)
            if inference_duration:
                inference_duration.observe(time.time() - start)
            stream_id = meta.get("stream_id", "unknown")
            if frames_processed:
                frames_processed.labels(stream=stream_id).inc()
            # publish detections
            det_msgs = []
            for cls_id, conf, x1, y1, x2, y2 in dets:
                box = self.normalize_box(x1, y1, x2, y2, w, h)
                det_msgs.append({
                    "stream_id": stream_id,
                    "frame_id": meta.get("frame_id"),
                    "ts": ts_now,
                    "capture_ts": cap_ts,
                    "class_id": int(cls_id),
                    "class": self.detector.class_names[int(cls_id)] if int(cls_id) < len(self.detector.class_names) else str(cls_id),
                    "confidence": float(conf),
                    "bbox": box,
                })
            if det_msgs:
                out = {"detections": json.dumps(det_msgs)}
                self.redis.xadd("detections", out, maxlen=10000, approximate=True)
                if detections_published:
                    detections_published.inc(len(det_msgs))
            self.redis.xack(stream_name, cfg.consumer_group, msg_id)
        except Exception as e:
            # don't ack on error
            pass

    def discover_streams(self) -> List[str]:
        self.connect_redis()
        found = []
        for key in self.redis.scan_iter(match="frames:*", count=100):
            found.append(key)
        for s in found:
            self.ensure_consumer_group(s)
        return found

    def reclaim_stale(self, streams_to_read: List[str]):
        """Reclaim pending messages from crashed consumers after idle timeout."""
        for stream_name in streams_to_read:
            try:
                resp = self.redis.xautoclaim(
                    stream_name, cfg.consumer_group, cfg.consumer_name,
                    min_idle_time=cfg.stale_threshold_ms * 100, count=10,
                )
                if resp and len(resp) >= 2 and resp[1]:
                    for msg_id, fields in resp[1]:
                        self.process_message(stream_name, msg_id, fields)
            except Exception:
                pass

    def run(self):
        self.connect_redis()
        streams_to_read: List[str] = []
        last_discovery = 0.0
        last_reclaim = 0.0
        while self.running:
            try:
                now = time.time()
                if now - last_discovery > 5:
                    streams_to_read = self.discover_streams()
                    if not streams_to_read:
                        streams_to_read = ["frames:stream1"]
                        self.ensure_consumer_group(streams_to_read[0])
                    last_discovery = now
                if now - last_reclaim > 30:
                    self.reclaim_stale(streams_to_read)
                    last_reclaim = now

                streams = {s: ">" for s in streams_to_read}
                res = self.redis.xreadgroup(cfg.consumer_group, cfg.consumer_name, streams, count=10, block=2000)
                if not res:
                    continue
                for stream_name, messages in res:
                    for msg_id, fields in messages:
                        self.process_message(stream_name, msg_id, fields)
            except Exception as e:
                time.sleep(1)

def start_metrics():
    if start_http_server:
        try:
            start_http_server(cfg.metrics_port)
        except Exception:
            pass
