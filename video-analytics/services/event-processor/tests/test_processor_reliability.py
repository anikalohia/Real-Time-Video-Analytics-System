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

from models import Alert, Event  # noqa: E402


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


def test_ack_failure_after_commit_does_not_duplicate_event(ep, monkeypatch):
    sid = str(uuid.uuid4())
    payload = {'detections': json.dumps([_det(sid)])}
    msg_id = ep.redis.xadd('detections', payload)
    ep.redis.xreadgroup(processor_mod.cfg.consumer_group, 'test', {'detections': '>'}, count=1)

    original_xack = ep.redis.xack
    calls = {'count': 0}

    def flaky_xack(*args, **kwargs):
        calls['count'] += 1
        if calls['count'] == 1:
            raise RuntimeError('redis unavailable')
        return original_xack(*args, **kwargs)

    monkeypatch.setattr(ep.redis, 'xack', flaky_xack)
    ep._handle_message(msg_id, payload)

    pending = ep.redis.xpending('detections', processor_mod.cfg.consumer_group)
    assert pending['pending'] == 1
    with ep.Session() as s:
        assert s.query(Event).count() == 1

    assert ep.flush() is True
    pending = ep.redis.xpending('detections', processor_mod.cfg.consumer_group)
    assert pending['pending'] == 0
    with ep.Session() as s:
        assert s.query(Event).count() == 1


def test_replayed_message_does_not_duplicate_events_or_alerts(ep):
    sid = str(uuid.uuid4())
    ep.rules = [
        {
            'id': str(uuid.uuid4()),
            'stream_id': sid,
            'name': 'person detected',
            'class_filter': 'person',
            'zone_polygon': None,
            'threshold_count': 1,
            'dwell_seconds': 0,
            'cooldown_seconds': 0,
            'webhook_url': None,
            'enabled': True,
        }
    ]
    payload = {'detections': json.dumps([_det(sid)])}
    msg_id = ep.redis.xadd('detections', payload)
    ep.redis.xreadgroup(processor_mod.cfg.consumer_group, 'test', {'detections': '>'}, count=1)

    ep._handle_message(msg_id, payload)
    ep.trackers.clear()
    ep.rule_engine._last_fired.clear()
    ep._handle_message(msg_id, payload)

    with ep.Session() as s:
        assert s.query(Event).count() == 1
        assert s.query(Alert).count() == 1


def test_alert_persistence_failure_is_retried_then_dead_lettered(ep, monkeypatch):
    monkeypatch.setattr(processor_mod.cfg, 'max_delivery_attempts', 2)
    monkeypatch.setattr(ep, 'persist_alerts', lambda _alerts: None)
    sid = str(uuid.uuid4())
    ep.rules = [
        {
            'id': str(uuid.uuid4()),
            'stream_id': sid,
            'name': 'person detected',
            'class_filter': 'person',
            'zone_polygon': None,
            'threshold_count': 1,
            'dwell_seconds': 0,
            'cooldown_seconds': 0,
            'webhook_url': None,
            'enabled': True,
        }
    ]
    payload = {'detections': json.dumps([_det(sid)])}
    msg_id = ep.redis.xadd('detections', payload)
    ep.redis.xreadgroup(processor_mod.cfg.consumer_group, 'test', {'detections': '>'}, count=1)

    ep._handle_message(msg_id, payload)
    assert ep.redis.xlen('dead-letter') == 0
    pending = ep.redis.xpending('detections', processor_mod.cfg.consumer_group)
    assert pending['pending'] == 1

    ep._handle_message(msg_id, payload)
    assert ep.redis.xlen('dead-letter') == 1
    pending = ep.redis.xpending('detections', processor_mod.cfg.consumer_group)
    assert pending['pending'] == 0
