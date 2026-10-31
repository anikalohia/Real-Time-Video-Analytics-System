import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    desc,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class Stream(Base):
    __tablename__ = 'streams'
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255))
    source_url = Column(Text)
    # Desired lifecycle state: running / stopped.
    status = Column(String(50), default='stopped', nullable=False)
    # Observed health: connected / reconnecting / failed / stopped.
    health = Column(String(50), default='stopped', nullable=False)
    target_fps = Column(Integer, default=10)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Event(Base):
    __tablename__ = 'events'
    id = Column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    stream_id = Column(Uuid(as_uuid=True))
    ts = Column(DateTime(timezone=True))
    class_ = Column('class', String(100))
    confidence = Column(Float)
    bbox = Column(JSON)
    track_id = Column(String(50), nullable=True)
    frame_id = Column(Integer, nullable=True)
    event_key = Column(String(255), nullable=True, unique=True)
    __table_args__ = (
        Index('ix_events_stream_ts', 'stream_id', desc('ts')),
        Index('ix_events_class_ts', 'class', desc('ts')),
        Index('ix_events_ts', desc('ts')),
    )


class Rule(Base):
    __tablename__ = 'rules'
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stream_id = Column(Uuid(as_uuid=True))
    name = Column(String(255))
    class_filter = Column(String(100), nullable=True)
    zone_polygon = Column(JSON, nullable=True)
    threshold_count = Column(Integer, default=1)
    dwell_seconds = Column(Integer, default=0)
    cooldown_seconds = Column(Integer, default=60)
    webhook_url = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True)
    __table_args__ = (Index('ix_rules_stream', 'stream_id'),)


class Alert(Base):
    __tablename__ = 'alerts'
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id = Column(Uuid(as_uuid=True))
    stream_id = Column(Uuid(as_uuid=True))
    ts = Column(DateTime(timezone=True), server_default=func.now())
    payload = Column(JSON)
    delivered = Column(Boolean, default=False)
    alert_key = Column(String(255), nullable=True, unique=True)
    __table_args__ = (Index('ix_alerts_ts', desc('ts')),)


class User(Base):
    __tablename__ = 'users'
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default='operator')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
