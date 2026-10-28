import json
import os
import sys
import time
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

pytest.importorskip('fakeredis')
import fakeredis  # noqa: E402
import processor as processor_mod  # noqa: E402
from processor import EventProcessor  # noqa: E402

from models import Event  # noqa: E402


@pytest.fixture
def ep(monkeypatch, tmp_path):
    monkeypatch.setattr(
        processor_mod.cfg, 'postgres_dsn', f"sqlite:///{tmp_path / 'reliability.db'}"
    )
    monkeypatch.setattr(processor_mod.cfg, 'batch_size', 1)
    monkeypatch.setattr(processor_mod.cfg, 'flush_interval', 0.0)
    ep = EventProcessor(create_schema=True)
    ep.redis = fakeredis.FakeStrictRedis(decode_responses=True)
    ep.redis.xgroup_create('detections', processor_mod.cfg.consumer_group, id='0', mkstream=True)
    return ep


def _det(stream_id, x=0.1):
    return {
        'stream_id': stream_id,
        'frame_id': 1,
        'ts': time.time(),
        'class': 'person',
        'confidence': 0.9,
        'bbox': {'x': x, 'y': 0.1, 'w': 0.2, 'h': 0.2},
    }


def test_message_is_acked_after_commit(ep):
    sid = str(uuid.uuid4())
    msg_id = ep.redis.xadd('detections', {'detections': json.dumps([_det(sid)])})
    ep.redis.xreadgroup(processor_mod.cfg.consumer_group, 'test', {'detections': '>'}, count=1)
    ep._handle_message(msg_id, {'detections': json.dumps([_det(sid)])})
    pending = ep.redis.xpending('detections', processor_mod.cfg.consumer_group)
    assert pending['pending'] == 0
    with ep.Session() as s:
        assert s.query(Event).count() >= 1


def test_buffer_is_bounded_when_database_is_down(ep, monkeypatch):
    monkeypatch.setattr(processor_mod.cfg, 'db_buffer_max', 2)
    monkeypatch.setattr(processor_mod.cfg, 'batch_size', 10)
    monkeypatch.setattr(processor_mod.cfg, 'track_iou_threshold', 1.0)
    monkeypatch.setattr(ep, 'flush', lambda: False)
    sid = str(uuid.uuid4())
    for i in range(4):
        ep.process_detections([_det(sid, x=0.1 * (i + 1))])
    assert len(ep.buffer) == 2


def test_malformed_payload_goes_to_dead_letter_after_retries(ep, monkeypatch):
    monkeypatch.setattr(processor_mod.cfg, 'max_delivery_attempts', 1)
    msg_id = ep.redis.xadd('detections', {'detections': 'not-json'})
    ep.redis.xreadgroup(processor_mod.cfg.consumer_group, 'test', {'detections': '>'}, count=1)
    ep._handle_message(msg_id, {'detections': 'not-json'})
    assert ep.redis.xlen('dead-letter') == 1
    pending = ep.redis.xpending('detections', processor_mod.cfg.consumer_group)
    assert pending['pending'] == 0
