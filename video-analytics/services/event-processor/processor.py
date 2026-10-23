import json
import time
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import redis
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ep_config import get_config
from models import Base, Event, Rule, Alert
from rules import RuleEngine


def to_uuid(value) -> Optional[uuid.UUID]:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None

try:
    from prometheus_client import Counter, Histogram, start_http_server
except ImportError:
    Counter = Histogram = None
    start_http_server = None


cfg = get_config()

if Counter:
    events_written = Counter("events_written_total", "Events written to DB")
    dedup_hits = Counter("dedup_hits_total", "Dedup hits")
    alerts_fired = Counter("alerts_fired_total", "Alerts fired", ["rule"])
else:
    events_written = dedup_hits = alerts_fired = None
if Histogram:
    db_write_duration = Histogram("db_write_duration_seconds", "DB write duration")
else:
    db_write_duration = None


class EventProcessor:
    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self.engine = create_engine(cfg.postgres_dsn)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.running = True
        self.buffer: List[Dict[str, Any]] = []
        self.last_flush = time.time()
        self.dedup = {}
        self.rule_engine = RuleEngine()
        self.rules: List[Dict[str, Any]] = []
        self.last_rules_refresh = 0.0

    def connect_redis(self):
        if self.redis:
            try:
                self.redis.ping()
                return
            except Exception:
                self.redis = None
        self.redis = redis.Redis(host=cfg.redis_host, port=cfg.redis_port, db=cfg.redis_db, decode_responses=True)
        self.redis.ping()

    def ensure_consumer_group(self):
        self.connect_redis()
        try:
            self.redis.xgroup_create("detections", cfg.consumer_group, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def refresh_rules(self, force: bool = False):
        if not force and time.time() - self.last_rules_refresh < 5:
            return
        session = self.Session()
        try:
            rules = session.execute(select(Rule)).scalars().all()
            self.rules = [
                {
                    "id": str(r.id),
                    "stream_id": str(r.stream_id),
                    "name": r.name,
                    "class_filter": r.class_filter,
                    "zone_polygon": r.zone_polygon,
                    "threshold_count": r.threshold_count,
                    "dwell_seconds": r.dwell_seconds,
                    "cooldown_seconds": r.cooldown_seconds,
                    "enabled": r.enabled,
                }
                for r in rules
            ]
            self.last_rules_refresh = time.time()
        except Exception:
            pass
        finally:
            session.close()

    def flush(self):
        if not self.buffer:
            return
        start = time.time()
        session = self.Session()
        try:
            for e in self.buffer:
                ev = Event(
                    stream_id=to_uuid(e["stream_id"]),
                    ts=e["ts"],
                    class_=e["class"],
                    confidence=e["confidence"],
                    bbox=e["bbox"],
                    track_id=e.get("track_id"),
                    frame_id=e.get("frame_id"),
                )
                session.add(ev)
            session.commit()
            if events_written:
                events_written.inc(len(self.buffer))
        except Exception:
            session.rollback()
        finally:
            session.close()
        if db_write_duration:
            db_write_duration.observe(time.time() - start)
        self.buffer.clear()
        self.last_flush = time.time()

    def persist_alerts(self, alerts: List[Dict[str, Any]]):
        if not alerts:
            return
        session = self.Session()
        try:
            for a in alerts:
                session.add(Alert(
                    rule_id=to_uuid(a["rule_id"]),
                    stream_id=to_uuid(a["stream_id"]),
                    ts=datetime.fromtimestamp(a["ts"], tz=timezone.utc),
                    payload=a["payload"],
                    delivered=True,
                ))
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    def broadcast(self, channel: str, data: Dict[str, Any]):
        try:
            self.connect_redis()
            self.redis.publish(channel, json.dumps(data, default=str))
        except Exception:
            pass

    def process_detections(self, dets: List[Dict[str, Any]]):
        for d in dets:
            key = (d["stream_id"], d.get("frame_id"), d["class"])
            if key in self.dedup:
                if dedup_hits:
                    dedup_hits.inc()
                continue
            self.dedup[key] = time.time()
            self.buffer.append({
                "stream_id": d["stream_id"],
                "ts": datetime.fromtimestamp(d["ts"], tz=timezone.utc),
                "class": d["class"],
                "confidence": d["confidence"],
                "bbox": d["bbox"],
                "track_id": d.get("track_id"),
                "frame_id": d.get("frame_id"),
            })
            if len(self.buffer) >= cfg.batch_size:
                self.flush()

        # prune dedup cache
        if len(self.dedup) > 100000:
            self.dedup.clear()

        # broadcast live detections per stream
        by_stream: Dict[str, List[Dict[str, Any]]] = {}
        for d in dets:
            by_stream.setdefault(d["stream_id"], []).append(d)
        for sid, items in by_stream.items():
            self.broadcast(f"live:{sid}", {"detections": items})

        # rule evaluation
        self.refresh_rules()
        for sid, items in by_stream.items():
            alerts = self.rule_engine.evaluate(items, self.rules, sid)
            if alerts:
                self.persist_alerts(alerts)
                for a in alerts:
                    if alerts_fired:
                        alerts_fired.labels(rule=a.get("rule_name") or "rule").inc()
                    self.broadcast("alerts", {
                        "id": str(a["rule_id"]) + "-" + str(int(a["ts"] * 1000)),
                        "rule_id": a["rule_id"],
                        "stream_id": a["stream_id"],
                        "ts": datetime.fromtimestamp(a["ts"], tz=timezone.utc).isoformat(),
                        "payload": a["payload"],
                    })

    def run(self):
        self.connect_redis()
        self.ensure_consumer_group()
        while self.running:
            try:
                res = self.redis.xreadgroup(cfg.consumer_group, cfg.consumer_name, {"detections": ">"}, count=10, block=5000)
                if not res:
                    if time.time() - self.last_flush > cfg.flush_interval:
                        self.flush()
                    continue
                for stream_name, messages in res:
                    for msg_id, fields in messages:
                        dets_json = fields.get("detections", "[]")
                        try:
                            dets = json.loads(dets_json)
                        except Exception:
                            dets = []
                        self.process_detections(dets)
                        self.redis.xack(stream_name, cfg.consumer_group, msg_id)
                if time.time() - self.last_flush > cfg.flush_interval:
                    self.flush()
            except Exception:
                time.sleep(1)


def start_metrics():
    if start_http_server:
        try:
            start_http_server(cfg.metrics_port)
        except Exception:
            pass
