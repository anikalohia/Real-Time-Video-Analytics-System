import asyncio
import base64
import json
import os
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import datetime

import redis
import redis.asyncio as aioredis
from api_config import get_config
from auth import (
    AUTH_ENABLED,
    create_access_token,
    get_current_user,
    hash_password,
    require_admin,
    verify_password,
)
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from schemas import LoginRequest, RuleCreate, RuleUpdate, StreamCreate, StreamResponse
from sqlalchemy import and_, create_engine, delete, desc, or_, select, text
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException
from validators import validate_stream_url, validate_webhook_url

from services.event_processor.models import Alert, Event, Rule, Stream, User

cfg = get_config()


def log_event(**fields):
    print(json.dumps({'service': 'api', **fields}, default=str), flush=True)


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, channel: str, ws: WebSocket):
        await ws.accept()
        self.active_connections.setdefault(channel, []).append(ws)

    def disconnect(self, channel: str, ws: WebSocket):
        if channel in self.active_connections and ws in self.active_connections[channel]:
            self.active_connections[channel].remove(ws)

    async def broadcast(self, channel: str, text: str):
        for c in list(self.active_connections.get(channel, [])):
            try:
                await c.send_text(text)
            except Exception:
                self.disconnect(channel, c)


manager = ConnectionManager()

if Counter:
    api_requests = Counter('api_http_requests_total', 'HTTP requests', ['method', 'path', 'status'])
    api_rate_limited = Counter('api_rate_limited_total', 'Rate-limited requests')
    websocket_messages = Counter(
        'api_websocket_messages_total', 'WebSocket fanout messages', ['channel']
    )
else:  # pragma: no cover
    api_requests = api_rate_limited = websocket_messages = None

if Histogram:
    api_latency = Histogram(
        'api_http_request_duration_seconds',
        'HTTP request duration',
        ['method', 'path'],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    )
else:  # pragma: no cover
    api_latency = None


async def redis_subscriber():
    """Subscribe to Redis pub/sub channels and fan out to websockets."""
    while True:
        try:
            r = aioredis.Redis(
                host=cfg.redis_host,
                port=cfg.redis_port,
                db=cfg.redis_db,
                decode_responses=True,
            )
            pubsub = r.pubsub()
            await pubsub.psubscribe('live:*', 'alerts')
            async for message in pubsub.listen():
                if message['type'] != 'pmessage':
                    continue
                channel = message['channel']
                if channel.startswith('live:'):
                    sid = channel.split(':', 1)[1]
                    if websocket_messages:
                        websocket_messages.labels(channel='live').inc()
                    await manager.broadcast(f'stream:{sid}', message['data'])
                elif channel == 'alerts':
                    if websocket_messages:
                        websocket_messages.labels(channel='alerts').inc()
                    await manager.broadcast('alerts', message['data'])
        except Exception as exc:
            log_event(event='redis_subscriber_error', error=str(exc))
            await asyncio.sleep(2)


def seed_admin_user():
    if not AUTH_ENABLED:
        return
    email = os.getenv('ADMIN_EMAIL', 'admin@example.com')
    password = os.getenv('ADMIN_PASSWORD', 'admin')
    if password == 'admin':
        log_event(event='insecure_admin_password', email=email)
    try:
        db = SessionLocal()
        exists = db.execute(select(User).where(User.email == email)).scalars().first()
        if not exists:
            db.add(User(email=email, password_hash=hash_password(password), role='admin'))
            db.commit()
        db.close()
    except Exception as exc:
        log_event(event='seed_admin_failed', error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_admin_user()
    task = None
    if not cfg.disable_subscriber:
        task = asyncio.create_task(redis_subscriber())
    yield
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title='Video Analytics API', version='1.0.0', lifespan=lifespan)

origins = [o.strip() for o in cfg.cors_origins.split(',') if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ['http://localhost:3000'],
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    message = exc.detail if isinstance(exc.detail, str) else 'request failed'
    return JSONResponse(
        status_code=exc.status_code,
        content={'error': {'code': f'http_{exc.status_code}', 'message': message}},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            'error': {
                'code': 'validation_error',
                'message': 'invalid request',
                'details': jsonable_encoder(exc.errors()),
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log_event(event='unhandled_api_error', path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={'error': {'code': 'internal_error', 'message': 'internal server error'}},
    )


@app.middleware('http')
async def observability_middleware(request: Request, call_next):
    request_id = request.headers.get('x-request-id') or uuid.uuid4().hex[:16]
    start = asyncio.get_event_loop().time()
    status_code = 500
    response = None
    try:
        response = await call_next(request)
        status_code = response.status_code
    finally:
        elapsed = asyncio.get_event_loop().time() - start
        route = request.scope.get('route')
        path = getattr(route, 'path', request.url.path)
        if api_requests:
            api_requests.labels(method=request.method, path=path, status=str(status_code)).inc()
        if api_latency:
            api_latency.labels(method=request.method, path=path).observe(elapsed)
    if response is None:
        response = JSONResponse(
            status_code=500,
            content={'error': {'code': 'internal_error', 'message': 'internal server error'}},
        )
    response.headers['x-request-id'] = request_id
    return response


engine = create_engine(cfg.postgres_dsn, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _uuid(value):
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _redis():
    return redis.Redis(
        host=cfg.redis_host,
        port=cfg.redis_port,
        db=cfg.redis_db,
        decode_responses=True,
    )


def _rate_limit(request: Request):
    limit = cfg.rate_limit_per_minute
    if limit <= 0:
        return
    key = f"ratelimit:{request.client.host if request.client else 'unknown'}:{request.url.path}"
    try:
        client = _redis()
        count = client.incr(key)
        if count == 1:
            client.expire(key, 60)
    except Exception:
        return
    if count > limit:
        if api_rate_limited:
            api_rate_limited.inc()
        raise HTTPException(status_code=429, detail='rate limit exceeded')


@app.get('/health')
@app.get('/api/health')
def health():
    checks = {}
    try:
        db = SessionLocal()
        db.execute(text('SELECT 1'))
        db.close()
        checks['database'] = 'ok'
    except Exception:
        checks['database'] = 'unavailable'
    try:
        _redis().ping()
        checks['redis'] = 'ok'
    except Exception:
        checks['redis'] = 'unavailable'
    status = 'ok' if all(v == 'ok' for v in checks.values()) else 'degraded'
    return {'status': status, 'service': 'api', 'checks': checks}


@app.get('/metrics')
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post('/api/auth/login')
def login(body: LoginRequest, request: Request, db=Depends(get_db)):
    _rate_limit(request)
    user = db.execute(select(User).where(User.email == body.email)).scalars().first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail='invalid credentials')
    token = create_access_token(user.email, user.role, expires_minutes=cfg.jwt_expires_minutes)
    return {'access_token': token, 'token_type': 'bearer', 'role': user.role}


@app.get('/api/auth/me')
def me(user=Depends(get_current_user)):
    return user


@app.post('/api/streams', response_model=StreamResponse)
def create_stream(
    s: StreamCreate,
    request: Request,
    db=Depends(get_db),
    _admin=Depends(require_admin),
):
    _rate_limit(request)
    if not validate_stream_url(s.source_url):
        raise HTTPException(status_code=400, detail='invalid or disallowed stream URL')
    st = Stream(
        name=s.name,
        source_url=s.source_url,
        status='stopped',
        health='stopped',
        target_fps=s.target_fps,
    )
    db.add(st)
    db.commit()
    db.refresh(st)
    return StreamResponse(
        id=str(st.id),
        name=st.name,
        source_url=st.source_url,
        status=st.status,
        health=st.health,
        target_fps=st.target_fps,
        created_at=st.created_at,
    )


@app.get('/api/streams')
def list_streams(db=Depends(get_db)):
    res = db.execute(select(Stream)).scalars().all()
    return [
        {
            'id': str(r.id),
            'name': r.name,
            'source_url': r.source_url,
            'status': r.status,
            'health': r.health,
            'target_fps': r.target_fps,
            'created_at': r.created_at,
        }
        for r in res
    ]


@app.get('/api/streams/{sid}/frame')
def get_stream_frame(sid: str, db=Depends(get_db)):
    stream = db.get(Stream, _uuid(sid))
    if not stream:
        raise HTTPException(404, 'stream not found')
    try:
        data = _redis().hgetall(f'latest:{stream.id}')
        if not data or not data.get('image_b64'):
            raise HTTPException(404, 'no frame available')
        image = base64.b64decode(data['image_b64'])
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, 'frame cache unavailable')
    return Response(
        content=image,
        media_type='image/jpeg',
        headers={
            'Cache-Control': 'no-store',
            'X-Frame-Timestamp': str(data.get('ts', '')),
        },
    )


@app.post('/api/streams/{sid}/start')
def start_stream(sid: str, request: Request, db=Depends(get_db), _admin=Depends(require_admin)):
    _rate_limit(request)
    st = db.get(Stream, _uuid(sid))
    if not st:
        raise HTTPException(404, 'stream not found')
    st.status = 'running'
    st.health = 'reconnecting'
    db.commit()
    return {'ok': True}


@app.post('/api/streams/{sid}/stop')
def stop_stream(sid: str, request: Request, db=Depends(get_db), _admin=Depends(require_admin)):
    _rate_limit(request)
    st = db.get(Stream, _uuid(sid))
    if not st:
        raise HTTPException(404, 'stream not found')
    st.status = 'stopped'
    st.health = 'stopped'
    db.commit()
    return {'ok': True}


@app.delete('/api/streams/{sid}')
def delete_stream(sid: str, request: Request, db=Depends(get_db), _admin=Depends(require_admin)):
    _rate_limit(request)
    stream_id = _uuid(sid)
    st = db.get(Stream, stream_id)
    if not st:
        raise HTTPException(404, 'stream not found')
    db.execute(delete(Event).where(Event.stream_id == stream_id))
    db.execute(delete(Alert).where(Alert.stream_id == stream_id))
    db.execute(delete(Rule).where(Rule.stream_id == stream_id))
    db.delete(st)
    db.commit()
    return {'ok': True}


def _event_dict(r: Event) -> dict:
    return {
        'id': r.id,
        'stream_id': str(r.stream_id) if r.stream_id else None,
        'ts': r.ts,
        'class': r.class_,
        'confidence': r.confidence,
        'bbox': r.bbox,
        'track_id': r.track_id,
        'frame_id': r.frame_id,
    }


@app.get('/api/events')
def get_events(
    stream_id: str | None = None,
    class_: str | None = Query(default=None, alias='class'),
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = None,
    db=Depends(get_db),
):
    q = select(Event).order_by(desc(Event.id), desc(Event.ts))
    if stream_id:
        stream_uuid = _uuid(stream_id)
        if stream_uuid is None:
            raise HTTPException(400, 'invalid stream_id')
        q = q.where(Event.stream_id == stream_uuid)
    if class_:
        q = q.where(Event.class_ == class_)
    if from_ts:
        q = q.where(Event.ts >= from_ts)
    if to_ts:
        q = q.where(Event.ts <= to_ts)
    if cursor:
        try:
            q = q.where(Event.id < int(cursor))
        except ValueError:
            raise HTTPException(400, 'invalid cursor')
    q = q.limit(limit + 1)
    rows = db.execute(q).scalars().all()
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = str(rows[-1].id)
    return {'items': [_event_dict(r) for r in rows], 'next_cursor': next_cursor}


@app.post('/api/rules')
def create_rule(
    body: RuleCreate,
    request: Request,
    db=Depends(get_db),
    _admin=Depends(require_admin),
):
    _rate_limit(request)
    stream_id = _uuid(body.stream_id)
    if stream_id is None or not db.get(Stream, stream_id):
        raise HTTPException(404, 'stream not found')
    if body.webhook_url and not validate_webhook_url(body.webhook_url):
        raise HTTPException(400, 'invalid or disallowed webhook URL')
    r = Rule(
        stream_id=stream_id,
        name=body.name,
        class_filter=body.class_filter,
        zone_polygon=body.zone_polygon,
        threshold_count=body.threshold_count,
        dwell_seconds=body.dwell_seconds,
        cooldown_seconds=body.cooldown_seconds,
        webhook_url=body.webhook_url,
        enabled=body.enabled,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return {'id': str(r.id)}


def _rule_dict(r: Rule) -> dict:
    return {
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


@app.get('/api/rules')
def list_rules(db=Depends(get_db)):
    res = db.execute(select(Rule)).scalars().all()
    return [_rule_dict(r) for r in res]


@app.patch('/api/rules/{rid}')
def update_rule(
    rid: str,
    body: RuleUpdate,
    request: Request,
    db=Depends(get_db),
    _admin=Depends(require_admin),
):
    _rate_limit(request)
    r = db.get(Rule, _uuid(rid))
    if not r:
        raise HTTPException(404, 'rule not found')
    updates = body.model_dump(exclude_unset=True)
    if 'webhook_url' in updates and updates['webhook_url']:
        if not validate_webhook_url(updates['webhook_url']):
            raise HTTPException(400, 'invalid or disallowed webhook URL')
    if 'zone_polygon' in updates and updates['zone_polygon'] is not None:
        zone = updates['zone_polygon']
        if len(zone) < 3 or any(len(p) != 2 or not all(0 <= v <= 1 for v in p) for p in zone):
            raise HTTPException(400, 'invalid zone_polygon')
    for k, v in updates.items():
        setattr(r, k, v)
    db.commit()
    return {'ok': True}


@app.delete('/api/rules/{rid}')
def delete_rule(rid: str, request: Request, db=Depends(get_db), _admin=Depends(require_admin)):
    _rate_limit(request)
    rule_id = _uuid(rid)
    r = db.get(Rule, rule_id)
    if not r:
        raise HTTPException(404, 'rule not found')
    db.execute(delete(Alert).where(Alert.rule_id == rule_id))
    db.delete(r)
    db.commit()
    return {'ok': True}


def _encode_alert_cursor(ts: datetime, alert_id: uuid.UUID) -> str:
    raw = f'{ts.isoformat()}|{alert_id}'
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_alert_cursor(value: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(value.encode()).decode()
        ts_value, id_value = raw.split('|', 1)
        return datetime.fromisoformat(ts_value), uuid.UUID(id_value)
    except Exception:
        raise HTTPException(400, 'invalid cursor')


@app.get('/api/alerts')
def get_alerts(
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = None,
    db=Depends(get_db),
):
    q = select(Alert).order_by(desc(Alert.ts), desc(Alert.id))
    if cursor:
        ts_value, alert_id = _decode_alert_cursor(cursor)
        q = q.where(
            or_(
                Alert.ts < ts_value,
                and_(Alert.ts == ts_value, Alert.id < alert_id),
            )
        )
    rows = db.execute(q.limit(limit + 1)).scalars().all()
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_alert_cursor(rows[-1].ts, rows[-1].id)
    items = [
        {
            'id': str(r.id),
            'rule_id': str(r.rule_id),
            'stream_id': str(r.stream_id),
            'ts': r.ts,
            'payload': r.payload,
            'delivered': r.delivered,
        }
        for r in rows
    ]
    return {'items': items, 'next_cursor': next_cursor}


@app.websocket('/ws/streams/{sid}')
async def ws_stream(ws: WebSocket, sid: str):
    await manager.connect(f'stream:{sid}', ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(f'stream:{sid}', ws)


@app.websocket('/ws/alerts')
async def ws_alerts(ws: WebSocket):
    await manager.connect('alerts', ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect('alerts', ws)
