import base64
import json
import os
import sys
import time

import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest.importorskip("fakeredis")

import fakeredis

import detector as detector_mod
from detector import DetectionWorker
from mock_detector import MockDetector


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setattr(detector_mod.cfg, "detector_backend", "mock")
    monkeypatch.setattr(detector_mod.cfg, "stale_threshold_ms", 100000)
    w = DetectionWorker()
    w.redis = fakeredis.FakeStrictRedis(decode_responses=True)
    return w


def make_fields(stream_id="stream1", capture_ts=None):
    img = np.zeros((360, 640, 3), np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    meta = {
        "stream_id": stream_id,
        "frame_id": 1,
        "ts": time.time(),
        "capture_ts": capture_ts if capture_ts is not None else time.time(),
        "width": 640,
        "height": 360,
        "format": "jpeg",
    }
    return {
        "metadata": json.dumps(meta),
        "image_b64": base64.b64encode(buf.tobytes()).decode("utf-8"),
    }


def create_group(worker, stream="frames:stream1"):
    try:
        worker.redis.xgroup_create(stream, detector_mod.cfg.consumer_group, id="0", mkstream=True)
    except Exception:
        pass


def test_decode_frame_roundtrip(worker):
    fields = make_fields()
    frame = worker.decode_frame(fields["image_b64"])
    assert frame.shape == (360, 640, 3)


class _StubDetector:
    class_names = MockDetector.class_names

    def detect(self, img):
        return [(0, 0.9, 10, 10, 100, 100)]


def test_process_message_publishes_detections(worker):
    worker.detector = _StubDetector()
    create_group(worker)
    worker.redis.xadd("frames:stream1", make_fields())
    msgs = worker.redis.xreadgroup(detector_mod.cfg.consumer_group, "w1", {"frames:stream1": ">"})
    _, message_list = msgs[0]
    msg_id, fields = message_list[0]
    worker.process_message("frames:stream1", msg_id, fields)

    entries = worker.redis.xrange("detections")
    assert len(entries) >= 1
    payload = json.loads(entries[0][1]["detections"])
    for d in payload:
        assert d["stream_id"] == "stream1"
        assert 0.0 <= d["bbox"]["x"] <= 1.0
        assert d["class"] in MockDetector.class_names


def test_stale_frame_is_dropped(monkeypatch):
    monkeypatch.setattr(detector_mod.cfg, "detector_backend", "mock")
    monkeypatch.setattr(detector_mod.cfg, "stale_threshold_ms", 300)
    w = DetectionWorker()
    w.redis = fakeredis.FakeStrictRedis(decode_responses=True)
    fields = make_fields(capture_ts=time.time() - 10)
    w.process_message("frames:stream1", "1-0", fields)
    assert len(w.redis.xrange("detections")) == 0


def test_normalize_box(worker):
    box = worker.normalize_box(0, 0, 320, 180, 640, 360)
    assert box["x"] == 0.0
    assert abs(box["w"] - 0.5) < 1e-9
    assert abs(box["h"] - 0.5) < 1e-9
