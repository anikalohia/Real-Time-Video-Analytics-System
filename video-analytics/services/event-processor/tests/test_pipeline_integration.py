import json
import os
import sys
import time
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest.importorskip("fakeredis")
import fakeredis

import processor as processor_mod
from processor import EventProcessor
from models import Stream, Rule, Event, Alert


@pytest.fixture
def ep(monkeypatch, tmp_path):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(processor_mod.cfg, "postgres_dsn", f"sqlite:///{db_file}")
    monkeypatch.setattr(processor_mod.cfg, "batch_size", 10)
    ep = EventProcessor()
    ep.redis = fakeredis.FakeStrictRedis(decode_responses=True)
    return ep


def _det(stream_id, cls="person", frame_id=1):
    return {
        "stream_id": stream_id,
        "frame_id": frame_id,
        "ts": time.time(),
        "class": cls,
        "confidence": 0.9,
        "bbox": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
    }


def test_detections_written_to_db(ep):
    sid = str(uuid.uuid4())
    ep.process_detections([_det(sid, frame_id=1), _det(sid, cls="car", frame_id=2)])
    ep.flush()
    with ep.Session() as s:
        events = s.query(Event).all()
    assert len(events) == 2
    classes = sorted(e.class_ for e in events)
    assert classes == ["car", "person"]


def test_dedup_same_frame_class(ep):
    sid = str(uuid.uuid4())
    ep.process_detections([_det(sid, frame_id=1)])
    ep.process_detections([_det(sid, frame_id=1)])
    ep.flush()
    with ep.Session() as s:
        events = s.query(Event).all()
    assert len(events) == 1


def test_rule_fires_and_alert_persisted(ep):
    with ep.Session() as s:
        st = Stream(name="s", source_url="sample.mp4", status="running")
        s.add(st)
        s.commit()
        s.refresh(st)
        sid = str(st.id)
        rule = Rule(stream_id=st.id, name="count>=2", class_filter="person",
                    zone_polygon=None, threshold_count=2, dwell_seconds=0,
                    cooldown_seconds=60, enabled=True)
        s.add(rule)
        s.commit()

    ep.refresh_rules(force=True)
    ep.process_detections([_det(sid, frame_id=1), _det(sid, frame_id=2)])
    ep.flush()

    with ep.Session() as s:
        alerts = s.query(Alert).all()
    assert len(alerts) == 1
    assert alerts[0].payload["count"] == 2


def test_broadcast_publishes_live_channel(ep):
    sid = str(uuid.uuid4())
    # subscribe and observe publish
    ps = ep.redis.pubsub()
    ps.subscribe(f"live:{sid}")
    ps.get_message(timeout=1)  # subscribe confirmation
    ep.process_detections([_det(sid, frame_id=1)])
    msg = ps.get_message(timeout=2)
    assert msg is not None
    data = json.loads(msg["data"])
    assert "detections" in data
