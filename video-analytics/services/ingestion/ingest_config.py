import os
from dataclasses import dataclass


@dataclass
class Config:
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_db: int = int(os.getenv("REDIS_DB", "0"))
    max_fps: int = int(os.getenv("MAX_FPS", "10"))
    sample_interval: int = int(os.getenv("SAMPLE_INTERVAL", "1"))  # process every Nth frame
    max_stream_len: int = int(os.getenv("MAX_STREAM_LEN", "1000"))
    reconnect_base_delay: float = float(os.getenv("RECONNECT_BASE_DELAY", "1.0"))
    reconnect_max_delay: float = float(os.getenv("RECONNECT_MAX_DELAY", "30.0"))
    stale_threshold_ms: int = int(os.getenv("STALE_THRESHOLD_MS", "300"))


def get_config() -> Config:
    return Config()
