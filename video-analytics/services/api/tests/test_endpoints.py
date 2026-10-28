import base64
import os
import sys
import uuid
from datetime import UTC, datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

pytest.importorskip('fakeredis')
pytest.importorskip('fastapi.testclient')
import fakeredis  # noqa: E402

DB_PATH = os.path.join(os.path.dirname(__file__), f'test_api_{uuid.uuid4().hex}.db')
os.environ['POSTGRES_DSN'] = f'sqlite:///{DB_PATH}'
os.environ['AUTH_ENABLED'] = '0'
os.environ['DISABLE_SUBSCRIBER'] = '1'
os.environ['ALLOW_PRIVATE_HOSTS'] = 'mediamtx'

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from services.event_processor.models import Alert, Base, Event  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    Base.metadata.create_all(main.engine)
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr(main, '_redis', lambda: fake)
    with TestClient(main.app) as c:
        c.fake_redis = fake
        yield c
    Base.metadata.drop_all(main.engine)


def _create_stream(client, name='cam'):
    r = client.post('/api/streams', json={'name': name, 'source_url': 'sample.mp4'})
    assert r.status_code == 200, r.text
    return r.json()


def test_health_returns_checks(client):
    r = client.get('/api/health')
    assert r.status_code == 200
    body = r.json()
    assert body['status'] in {'ok', 'degraded'}
    assert 'database' in body['checks']


def test_create_and_list_stream_has_health(client):
    stream = _create_stream(client, 'lobby')
    assert stream['health'] == 'stopped'
    assert stream['status'] == 'stopped'
    r = client.get('/api/streams')
    assert r.status_code == 200
    assert r.json()[0]['health'] == 'stopped'


def test_invalid_url_uses_error_envelope(client):
    r = client.post('/api/streams', json={'name': 'bad', 'source_url': 'http://169.254.169.254/x'})
    assert r.status_code == 400
    body = r.json()
    assert body['error']['code'] == 'http_400'


def test_private_rtsp_allowed_only_with_allowlist(client):
    allowed = client.post(
        '/api/streams',
        json={'name': 'demo', 'source_url': 'rtsp://mediamtx:8554/demo'},
    )
    assert allowed.status_code == 200
    blocked = client.post(
        '/api/streams',
        json={'name': 'evil', 'source_url': 'rtsp://127.0.0.1:8554/demo'},
    )
    assert blocked.status_code == 400


def test_events_pagination_envelope(client):
    stream = _create_stream(client)
    sid = uuid.UUID(stream['id'])
    with main.SessionLocal() as db:
        for i in range(3):
            db.add(
                Event(
                    stream_id=sid,
                    ts=datetime.now(UTC),
                    class_='person',
                    confidence=0.9,
                    bbox={'x': 0.1, 'y': 0.1, 'w': 0.2, 'h': 0.2},
                )
            )
        db.commit()
    r = client.get('/api/events?limit=2')
    assert r.status_code == 200
    body = r.json()
    assert len(body['items']) == 2
    assert body['next_cursor']
    r2 = client.get(f"/api/events?limit=2&cursor={body['next_cursor']}")
    assert len(r2.json()['items']) == 1
    assert r2.json()['next_cursor'] is None


def test_alerts_pagination_envelope(client):
    stream = _create_stream(client)
    sid = uuid.UUID(stream['id'])
    with main.SessionLocal() as db:
        for i in range(3):
            db.add(
                Alert(
                    rule_id=uuid.uuid4(),
                    stream_id=sid,
                    ts=datetime.now(UTC),
                    payload={'n': i},
                )
            )
        db.commit()
    r = client.get('/api/alerts?limit=2')
    assert r.status_code == 200
    body = r.json()
    assert len(body['items']) == 2
    assert body['next_cursor']
    r2 = client.get(f"/api/alerts?limit=2&cursor={body['next_cursor']}")
    assert r2.status_code == 200
    assert len(r2.json()['items']) == 1
    assert r2.json()['next_cursor'] is None


def test_frame_endpoint_returns_jpeg(client):
    stream = _create_stream(client)
    client.fake_redis.hset(
        f"latest:{stream['id']}",
        mapping={
            'image_b64': base64.b64encode(b'\xff\xd8fakejpeg\xff\xd9').decode(),
            'ts': '123.4',
        },
    )
    r = client.get(f"/api/streams/{stream['id']}/frame")
    assert r.status_code == 200
    assert r.headers['content-type'] == 'image/jpeg'
    assert r.content.startswith(b'\xff\xd8')


def test_frame_missing_returns_404(client):
    stream = _create_stream(client)
    r = client.get(f"/api/streams/{stream['id']}/frame")
    assert r.status_code == 404
    assert r.json()['error']['code'] == 'http_404'


def test_rule_create_validates_stream_and_zone(client):
    stream = _create_stream(client)
    body = {
        'stream_id': stream['id'],
        'name': 'zone',
        'class_filter': 'person',
        'zone_polygon': [[0, 0], [1, 0], [1, 1]],
        'threshold_count': 2,
        'dwell_seconds': 3,
        'cooldown_seconds': 30,
    }
    r = client.post('/api/rules', json=body)
    assert r.status_code == 200, r.text
    rules = client.get('/api/rules').json()
    assert len(rules) == 1
    assert rules[0]['dwell_seconds'] == 3
    missing = client.post('/api/rules', json={**body, 'stream_id': str(uuid.uuid4())})
    assert missing.status_code == 404
    invalid_zone = client.post('/api/rules', json={**body, 'zone_polygon': [[0, 0], [1, 1]]})
    assert invalid_zone.status_code == 422


def test_delete_stream_removes_dependents(client):
    stream = _create_stream(client)
    sid = uuid.UUID(stream['id'])
    with main.SessionLocal() as db:
        db.add(
            Event(
                stream_id=sid,
                ts=datetime.now(UTC),
                class_='person',
                confidence=0.9,
                bbox={'x': 0, 'y': 0, 'w': 1, 'h': 1},
            )
        )
        db.commit()
    r = client.delete(f"/api/streams/{stream['id']}")
    assert r.status_code == 200
    assert client.get('/api/events').json()['items'] == []
