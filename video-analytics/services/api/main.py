import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from typing import List, Optional
from datetime import datetime

import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import create_engine, select, desc
from sqlalchemy.orm import sessionmaker
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from api_config import get_config
from schemas import StreamCreate, StreamResponse
from validators import validate_stream_url
from auth import (
    AUTH_ENABLED,
    create_access_token,
    hash_password,
    verify_password,
    get_current_user,
    require_admin,
)
from services.event_processor.models import Stream, Event, Rule, Alert, User

cfg = get_config()


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, List[WebSocket]] = {}

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


async def redis_subscriber():
    """Subscribe to Redis pub/sub channels and fan out to websockets."""
    while True:
        try:
            r = aioredis.Redis(host=cfg.redis_host, port=cfg.redis_port, db=cfg.redis_db, decode_responses=True)
            pubsub = r.pubsub()
            await pubsub.psubscribe("live:*", "alerts")
            async for message in pubsub.listen():
                if message["type"] != "pmessage":
                    continue
                channel = message["channel"]
                if channel.startswith("live:"):
                    sid = channel.split(":", 1)[1]
                    await manager.broadcast(f"stream:{sid}", message["data"])
                elif channel == "alerts":
                    await manager.broadcast("alerts", message["data"])
        except Exception:
            await asyncio.sleep(2)


def seed_admin_user():
    if not AUTH_ENABLED:
        return
    email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    password = os.getenv("ADMIN_PASSWORD", "admin")
    try:
        db = SessionLocal()
        exists = db.execute(select(User).where(User.email == email)).scalars().first()
        if not exists:
            db.add(User(email=email, password_hash=hash_password(password), role="admin"))
            db.commit()
        db.close()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_admin_user()
    task = asyncio.create_task(redis_subscriber())
    yield
    task.cancel()


app = FastAPI(title="Video Analytics API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = create_engine(cfg.postgres_dsn)
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


@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginRequest, db=Depends(get_db)):
    user = db.execute(select(User).where(User.email == body.email)).scalars().first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = create_access_token(user.email, user.role)
    return {"access_token": token, "token_type": "bearer", "role": user.role}


@app.get("/api/auth/me")
def me(user=Depends(get_current_user)):
    return user


@app.post("/api/streams", response_model=StreamResponse)
def create_stream(s: StreamCreate, db=Depends(get_db), _admin=Depends(require_admin)):
    if not validate_stream_url(s.source_url):
        raise HTTPException(status_code=400, detail="invalid or disallowed stream URL")
    st = Stream(name=s.name, source_url=s.source_url, status="stopped", target_fps=s.target_fps)
    db.add(st)
    db.commit()
    db.refresh(st)
    return StreamResponse(id=str(st.id), name=st.name, source_url=st.source_url,
                          status=st.status, target_fps=st.target_fps, created_at=st.created_at)


@app.get("/api/streams")
def list_streams(db=Depends(get_db)):
    res = db.execute(select(Stream)).scalars().all()
    return [{"id": str(r.id), "name": r.name, "source_url": r.source_url, "status": r.status,
             "target_fps": r.target_fps, "created_at": r.created_at} for r in res]


@app.post("/api/streams/{sid}/start")
def start_stream(sid: str, db=Depends(get_db), _admin=Depends(require_admin)):
    st = db.get(Stream, _uuid(sid))
    if not st:
        raise HTTPException(404, "stream not found")
    st.status = "running"
    db.commit()
    return {"ok": True}


@app.post("/api/streams/{sid}/stop")
def stop_stream(sid: str, db=Depends(get_db), _admin=Depends(require_admin)):
    st = db.get(Stream, _uuid(sid))
    if not st:
        raise HTTPException(404, "stream not found")
    st.status = "stopped"
    db.commit()
    return {"ok": True}


@app.delete("/api/streams/{sid}")
def delete_stream(sid: str, db=Depends(get_db), _admin=Depends(require_admin)):
    st = db.get(Stream, _uuid(sid))
    if not st:
        raise HTTPException(404, "stream not found")
    db.delete(st)
    db.commit()
    return {"ok": True}


@app.get("/api/events")
def get_events(
    stream_id: Optional[str] = None,
    class_: Optional[str] = None,
    from_ts: Optional[datetime] = None,
    to_ts: Optional[datetime] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
    db=Depends(get_db),
):
    q = select(Event).order_by(desc(Event.ts)).limit(min(limit, 500))
    if stream_id:
        q = q.where(Event.stream_id == _uuid(stream_id))
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
            pass
    res = db.execute(q).scalars().all()
    return [{"id": r.id, "stream_id": str(r.stream_id) if r.stream_id else None, "ts": r.ts,
             "class": r.class_, "confidence": r.confidence, "bbox": r.bbox,
             "track_id": r.track_id, "frame_id": r.frame_id} for r in res]


@app.post("/api/rules")
def create_rule(body: dict, db=Depends(get_db), _admin=Depends(require_admin)):
    r = Rule(
        stream_id=body.get("stream_id"),
        name=body.get("name", "rule"),
        class_filter=body.get("class_filter"),
        zone_polygon=body.get("zone_polygon"),
        threshold_count=body.get("threshold_count", 1),
        dwell_seconds=body.get("dwell_seconds", 0),
        cooldown_seconds=body.get("cooldown_seconds", 60),
        enabled=body.get("enabled", True),
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return {"id": str(r.id)}


@app.get("/api/rules")
def list_rules(db=Depends(get_db)):
    res = db.execute(select(Rule)).scalars().all()
    return [{"id": str(r.id), "stream_id": str(r.stream_id), "name": r.name,
             "class_filter": r.class_filter, "zone_polygon": r.zone_polygon,
             "threshold_count": r.threshold_count, "dwell_seconds": r.dwell_seconds,
             "cooldown_seconds": r.cooldown_seconds, "enabled": r.enabled} for r in res]


@app.patch("/api/rules/{rid}")
def update_rule(rid: str, body: dict, db=Depends(get_db), _admin=Depends(require_admin)):
    r = db.get(Rule, _uuid(rid))
    if not r:
        raise HTTPException(404, "rule not found")
    for k in ("name", "class_filter", "zone_polygon", "threshold_count", "dwell_seconds", "cooldown_seconds", "enabled"):
        if k in body:
            setattr(r, k, body[k])
    db.commit()
    return {"ok": True}


@app.get("/api/alerts")
def get_alerts(limit: int = 100, db=Depends(get_db)):
    res = db.execute(select(Alert).order_by(desc(Alert.ts)).limit(min(limit, 500))).scalars().all()
    return [{"id": str(r.id), "rule_id": str(r.rule_id), "stream_id": str(r.stream_id),
             "ts": r.ts, "payload": r.payload} for r in res]


@app.websocket("/ws/streams/{sid}")
async def ws_stream(ws: WebSocket, sid: str):
    await manager.connect(f"stream:{sid}", ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(f"stream:{sid}", ws)


@app.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket):
    await manager.connect("alerts", ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect("alerts", ws)
