import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import redis
from ep_config import get_config
from rules import RuleEngine
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from tracker import IoUTracker
from webhooks import WebhookDispatcher

from models import Alert, Base, Event, Rule

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
except ImportError:  # pragma: no cover
    Counter = Histogram = Gauge = None
    start_http_server = None


def to_uuid(value) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def log_event(**fields):
    print(json.dumps({'service': 'event-processor', **fields}, default=str), flush=True)


cfg = get_config()

if Counter:
    events_written = Counter('ep_events_written_total', 'Events written to DB')
    dedup_hits = Counter('ep_dedup_hits_total', 'Detections folded into an existing track')
    alerts_fired = Counter('ep_alerts_fired_total', 'Alerts fired', ['rule'])
    events_dropped = Counter(
        'ep_events_dropped_total', 'Events dropped before DB write', ['reason']
    )
    db_write_errors = Counter('ep_db_write_errors_total', 'DB write failures')
    messages_dead_lettered = Counter(
        'ep_messages_dead_lettered_total',
        'Messages moved to the dead-letter stream',
        ['reason'],
    )
else:  # pragma: no cover
    events_written = dedup_hits = alerts_fired = events_dropped = None
    db_write_errors = messages_dead_lettered = None

if Histogram:
    db_write_duration = Histogram('ep_db_write_duration_seconds', 'DB write duration')
    pipeline_latency = Histogram(
        'ep_pipeline_latency_seconds',
        'Per-stage pipeline latency',
        ['stage'],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )
else:  # pragma: no cover
    db_write_duration = pipeline_latency = None

if Gauge:
    redis_stream_length = Gauge('ep_redis_stream_length', 'Redis stream length', ['stream'])
    consumer_lag = Gauge('ep_consumer_lag', 'Approximate consumer group lag', ['stream', 'group'])
    active_tracks = Gauge('ep_active_tracks', 'Active tracks per stream', ['stream'])
else:  # pragma: no cover
    redis_stream_length = consumer_lag = active_tracks = None


class EventProcessor:
    def __init__(self, create_schema: bool = False):
        self.redis: redis.Redis | None = None
        self.engine = create_engine(cfg.postgres_dsn)
        if create_schema:
            Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.running = True
        self.buffer: list[dict[str, Any]] = []
        self.pending_acks: list[tuple[str, str]] = []
        self.last_flush = time.time()
        self.rule_engine = RuleEngine()
        self.rules: list[dict[str, Any]] = []
        self.last_rules_refresh = 0.0
        self.trackers: dict[str, IoUTracker] = {}
        self.webhooks = WebhookDispatcher(
            self._mark_webhook_delivery,
            timeout=cfg.webhook_timeout,
            max_attempts=cfg.webhook_max_attempts,
        )

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

    def ensure_consumer_group(self):
        self.connect_redis()
        try:
            self.redis.xgroup_create('detections', cfg.consumer_group, id='0', mkstream=True)
        except redis.ResponseError as exc:
            if 'BUSYGROUP' not in str(exc):
                raise

    def refresh_rules(self, force: bool = False):
        if not force and time.time() - self.last_rules_refresh < 5:
            return
        session = self.Session()
        try:
            rules = session.execute(select(Rule)).scalars().all()
            self.rules = [
                {
                    'id': str(r.id),
                    'stream_id': str(r.stream_id),
                    'name': r.name,
                    'class_filter': r.class_filter,
                    'zone_polygon': r.zone_polygon,
                    'threshold_count': r.threshold_count,
                    'dwell_seconds': r.dwell_seconds,
                    'cooldown_seconds': r.cooldown_seconds,
                    'webhook_url': r.webhook_url,
                    'enabled': r.enabled,
                }
                for r in rules
            ]
            self.last_rules_refresh = time.time()
        except Exception:
            pass
        finally:
            session.close()

    def _mark_webhook_delivery(self, alert_id: str, delivered: bool):
        session = self.Session()
        try:
            alert = session.get(Alert, to_uuid(alert_id))
            if alert is not None:
                alert.delivered = delivered
                session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    def flush(self) -> bool:
        if not self.buffer and not self.pending_acks:
            return True
        start = time.time()
        session = self.Session()
        try:
            if self.buffer:
                for e in self.buffer:
                    session.add(
                        Event(
                            stream_id=to_uuid(e['stream_id']),
                            ts=e['ts'],
                            class_=e['class'],
                            confidence=e['confidence'],
                            bbox=e['bbox'],
                            track_id=e.get('track_id'),
                            frame_id=e.get('frame_id'),
                        )
                    )
                session.commit()
                if events_written:
                    events_written.inc(len(self.buffer))
            # Ack only after a successful commit (or when there was nothing to write).
            if self.pending_acks:
                by_stream: dict[str, list[str]] = {}
                for stream_name, msg_id in self.pending_acks:
                    by_stream.setdefault(stream_name, []).append(msg_id)
                for stream_name, ids in by_stream.items():
                    self.redis.xack(stream_name, cfg.consumer_group, *ids)
                self.pending_acks.clear()
            self.buffer.clear()
            self.last_flush = time.time()
            return True
        except Exception as exc:
            session.rollback()
            if db_write_errors:
                db_write_errors.inc()
            log_event(event='db_write_error', error=str(exc))
            return False
        finally:
            session.close()
            if db_write_duration:
                db_write_duration.observe(time.time() - start)

    def persist_alerts(self, alerts: list[dict[str, Any]]):
        if not alerts:
            return
        session = self.Session()
        alert_ids: list[uuid.UUID] = []
        pending_webhooks: list[tuple[str, str, dict]] = []
        try:
            for a in alerts:
                alert = Alert(
                    rule_id=to_uuid(a['rule_id']),
                    stream_id=to_uuid(a['stream_id']),
                    ts=datetime.fromtimestamp(a['ts'], tz=UTC),
                    payload=a['payload'],
                    delivered=not bool(a.get('webhook_url')),
                )
                session.add(alert)
                session.flush()
                alert_ids.append(alert.id)
                if a.get('webhook_url'):
                    pending_webhooks.append(
                        (
                            str(alert.id),
                            a['webhook_url'],
                            {
                                'alert_id': str(alert.id),
                                'rule_id': str(a['rule_id']),
                                'rule_name': a.get('rule_name'),
                                'stream_id': str(a['stream_id']),
                                'ts': a['ts'],
                                'payload': a['payload'],
                            },
                        )
                    )
            session.commit()
        except Exception as exc:
            session.rollback()
            if db_write_errors:
                db_write_errors.inc()
            log_event(event='alert_write_error', error=str(exc))
            return []
        finally:
            session.close()
        # Deliver only after the alert is durably committed.
        for alert_id, url, payload in pending_webhooks:
            self.webhooks.submit(alert_id, url, payload)
        return alert_ids

    def broadcast(self, channel: str, data: dict[str, Any]):
        try:
            self.connect_redis()
            self.redis.publish(channel, json.dumps(data, default=str))
        except Exception:
            pass

    def _tracker(self, stream_id: str) -> IoUTracker:
        tracker = self.trackers.get(stream_id)
        if tracker is None:
            tracker = IoUTracker(
                iou_threshold=cfg.track_iou_threshold,
                ttl_seconds=cfg.track_ttl_seconds,
            )
            self.trackers[stream_id] = tracker
        return tracker

    def process_detections(
        self, dets: list[dict[str, Any]], ack_ref: tuple[str, str] | None = None
    ) -> int:
        now = time.time()
        events_added = 0
        by_stream: dict[str, list[dict[str, Any]]] = {}
        for det in dets:
            by_stream.setdefault(str(det.get('stream_id', 'unknown')), []).append(det)

        for sid, items in by_stream.items():
            tracker = self._tracker(sid)
            tracked = tracker.update(items, now)
            if active_tracks:
                active_tracks.labels(stream=sid).set(tracker.active_count())

            for det in tracked:
                if tracker.should_log(det, cfg.event_log_interval, now):
                    tracker.mark_logged(det['track_id'], now)
                    if len(self.buffer) >= cfg.db_buffer_max:
                        # First try to drain; if the DB is still down, shed the
                        # oldest event rather than growing without bound.
                        self.flush()
                    if len(self.buffer) >= cfg.db_buffer_max:
                        dropped = self.buffer.pop(0)
                        if events_dropped:
                            events_dropped.labels(reason='db_buffer_full').inc()
                        log_event(
                            event='event_dropped',
                            reason='db_buffer_full',
                            stream_id=dropped.get('stream_id'),
                        )
                    self.buffer.append(
                        {
                            'stream_id': det.get('stream_id', sid),
                            'ts': datetime.fromtimestamp(float(det.get('ts', now)), tz=UTC),
                            'class': det.get('class', 'unknown'),
                            'confidence': float(det.get('confidence', 0.0)),
                            'bbox': det.get('bbox'),
                            'track_id': det.get('track_id'),
                            'frame_id': det.get('frame_id'),
                        }
                    )
                    events_added += 1
                else:
                    if dedup_hits:
                        dedup_hits.inc()

                if pipeline_latency:
                    publish_ts = det.get('publish_ts') or det.get('ts')
                    if publish_ts:
                        pipeline_latency.labels(stage='delivery').observe(
                            max(0.0, now - float(publish_ts))
                        )

            self.broadcast(f'live:{sid}', {'detections': tracked, 'ts': now})

            alerts = self.rule_engine.evaluate(tracked, self.rules, sid, now=now)
            if alerts:
                alert_ids = self.persist_alerts(alerts)
                for alert, alert_id in zip(alerts, alert_ids):
                    if alerts_fired:
                        alerts_fired.labels(rule=alert.get('rule_name') or 'rule').inc()
                    self.broadcast(
                        'alerts',
                        {
                            'id': str(alert_id),
                            'rule_id': alert['rule_id'],
                            'stream_id': alert['stream_id'],
                            'ts': datetime.fromtimestamp(alert['ts'], tz=UTC).isoformat(),
                            'payload': alert['payload'],
                            'delivered': not bool(alert.get('webhook_url')),
                        },
                    )

        if ack_ref:
            self.pending_acks.append(ack_ref)
        if len(self.buffer) >= cfg.batch_size or (
            time.time() - self.last_flush >= cfg.flush_interval
        ):
            self.flush()
        return events_added

    def _retry_count(self, msg_id: str) -> int:
        key = 'retry:detections'
        attempts = int(self.redis.hincrby(key, msg_id, 1))
        self.redis.expire(key, 3600)
        return attempts

    def _dead_letter(self, msg_id: str, fields: dict, reason: str):
        try:
            self.redis.xadd(
                'dead-letter',
                {
                    'source_stream': 'detections',
                    'source_id': msg_id,
                    'reason': reason,
                    'fields': json.dumps(fields, default=str),
                },
                maxlen=10000,
                approximate=True,
            )
            self.redis.xack('detections', cfg.consumer_group, msg_id)
            if messages_dead_lettered:
                messages_dead_lettered.labels(reason=reason).inc()
        except Exception:
            pass

    def _handle_message(self, msg_id: str, fields: dict[str, str]):
        try:
            dets = json.loads(fields.get('detections', '[]'))
            if not isinstance(dets, list):
                raise ValueError('detections payload is not a list')
        except Exception as exc:
            attempts = self._retry_count(msg_id)
            log_event(
                event='detections_parse_error', msg_id=msg_id, attempt=attempts, error=str(exc)
            )
            if attempts >= cfg.max_delivery_attempts:
                self._dead_letter(msg_id, fields, 'parse_error')
            return
        self.process_detections(dets, ack_ref=('detections', msg_id))

    def reclaim_stale(self, min_idle_ms: int = 60000, count: int = 10):
        """Recover detections left pending by a crashed event processor."""
        try:
            result = self.redis.xautoclaim(
                'detections',
                cfg.consumer_group,
                cfg.consumer_name,
                min_idle_time=min_idle_ms,
                start_id='0-0',
                count=count,
            )
        except Exception:
            return
        claimed = result[1] if len(result) > 1 else []
        for msg_id, fields in claimed:
            if fields:
                self._handle_message(msg_id, fields)

    def refresh_stream_metrics(self):
        try:
            if redis_stream_length:
                redis_stream_length.labels(stream='detections').set(self.redis.xlen('detections'))
            if consumer_lag:
                groups = self.redis.xinfo_groups('detections')
                for group in groups:
                    if group.get('name') == cfg.consumer_group:
                        lag = group.get('lag')
                        if lag is None:
                            lag = group.get('pending', 0)
                        consumer_lag.labels(stream='detections', group=cfg.consumer_group).set(lag)
        except Exception:
            pass

    def run(self):
        self.connect_redis()
        self.ensure_consumer_group()
        self.refresh_rules(force=True)
        log_event(event='event_processor_started', consumer=cfg.consumer_name)
        last_metrics = 0.0
        last_reclaim = 0.0
        last_rules = time.time()
        while self.running:
            try:
                res = self.redis.xreadgroup(
                    cfg.consumer_group,
                    cfg.consumer_name,
                    {'detections': '>'},
                    count=10,
                    block=1000,
                )
                if res:
                    for _stream_name, messages in res:
                        for msg_id, fields in messages:
                            self._handle_message(msg_id, fields)
                now = time.time()
                if now - last_metrics > 5:
                    self.refresh_stream_metrics()
                    last_metrics = now
                if now - last_reclaim > 10:
                    self.reclaim_stale()
                    last_reclaim = now
                if now - last_rules > 5:
                    self.refresh_rules(force=True)
                    last_rules = now
                if time.time() - self.last_flush > cfg.flush_interval:
                    self.flush()
            except Exception as exc:
                log_event(event='event_processor_loop_error', error=str(exc))
                try:
                    self.connect_redis()
                except Exception:
                    pass
                time.sleep(1)
        self.flush()
        self.webhooks.close()


def start_metrics():
    if start_http_server:
        try:
            start_http_server(cfg.metrics_port)
        except Exception:
            pass
