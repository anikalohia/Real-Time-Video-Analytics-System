from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class StreamCreate(BaseModel):
    name: str
    source_url: str
    target_fps: int = 10


class StreamResponse(BaseModel):
    id: str
    name: str
    source_url: str
    status: str
    target_fps: int
    created_at: datetime


class EventQuery(BaseModel):
    stream_id: Optional[str] = None
    class_: Optional[str] = Field(default=None, alias="class")
    from_ts: Optional[datetime] = None
    to_ts: Optional[datetime] = None
    limit: int = 50
    cursor: Optional[str] = None
