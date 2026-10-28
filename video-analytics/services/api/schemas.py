from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class StreamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_url: str = Field(min_length=1)
    target_fps: int = Field(default=10, ge=1, le=60)


class StreamResponse(BaseModel):
    id: str
    name: str
    source_url: str
    status: str
    health: str
    target_fps: int
    created_at: datetime


class EventQuery(BaseModel):
    stream_id: str | None = None
    class_: str | None = Field(default=None, alias='class')
    from_ts: datetime | None = None
    to_ts: datetime | None = None
    limit: int = 50
    cursor: str | None = None


class RuleCreate(BaseModel):
    stream_id: str
    name: str = Field(default='rule', min_length=1, max_length=255)
    class_filter: str | None = None
    zone_polygon: list[list[float]] | None = None
    threshold_count: int = Field(default=1, ge=1)
    dwell_seconds: int = Field(default=0, ge=0)
    cooldown_seconds: int = Field(default=60, ge=0)
    webhook_url: str | None = None
    enabled: bool = True

    @field_validator('zone_polygon')
    @classmethod
    def validate_zone(cls, value):
        if value is None:
            return value
        if len(value) < 3:
            raise ValueError('zone_polygon needs at least 3 points')
        for point in value:
            if len(point) != 2 or not all(0 <= v <= 1 for v in point):
                raise ValueError('zone_polygon points must be normalized [x, y] pairs')
        return value


class RuleUpdate(BaseModel):
    name: str | None = None
    class_filter: str | None = None
    zone_polygon: list[list[float]] | None = None
    threshold_count: int | None = Field(default=None, ge=1)
    dwell_seconds: int | None = Field(default=None, ge=0)
    cooldown_seconds: int | None = Field(default=None, ge=0)
    webhook_url: str | None = None
    enabled: bool | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class EventItem(BaseModel):
    id: int
    stream_id: str | None
    ts: datetime
    class_: str = Field(alias='class')
    confidence: float | None
    bbox: dict | None
    track_id: str | None
    frame_id: int | None


class EventPage(BaseModel):
    items: list[dict]
    next_cursor: str | None = None


class AlertPage(BaseModel):
    items: list[dict]
    next_cursor: str | None = None
