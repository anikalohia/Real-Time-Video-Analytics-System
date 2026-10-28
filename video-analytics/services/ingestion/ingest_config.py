import os
from dataclasses import dataclass


@dataclass
class Config:
    redis_host: str = os.getenv('REDIS_HOST', 'localhost')
    redis_port: int = int(os.getenv('REDIS_PORT', '6379'))
    redis_db: int = int(os.getenv('REDIS_DB', '0'))
    max_fps: int = int(os.getenv('MAX_FPS', '10'))
    max_stream_len: int = int(os.getenv('MAX_STREAM_LEN', '1000'))
    reconnect_base_delay: float = float(os.getenv('RECONNECT_BASE_DELAY', '1.0'))
    reconnect_max_delay: float = float(os.getenv('RECONNECT_MAX_DELAY', '30.0'))
    metrics_port: int = int(os.getenv('METRICS_PORT', '8001'))
    latest_frame_ttl: int = int(os.getenv('LATEST_FRAME_TTL', '10'))
    manager_poll_seconds: float = float(os.getenv('MANAGER_POLL_SECONDS', '2.0'))


def get_config() -> Config:
    return Config()
