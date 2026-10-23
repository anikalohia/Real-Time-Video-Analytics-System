import os
from dataclasses import dataclass


@dataclass
class Config:
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_db: int = int(os.getenv("REDIS_DB", "0"))
    postgres_dsn: str = os.getenv("POSTGRES_DSN", "postgresql://user:pass@localhost:5432/analytics")
    batch_size: int = int(os.getenv("BATCH_SIZE", "10"))
    flush_interval: float = float(os.getenv("FLUSH_INTERVAL", "1.0"))
    consumer_group: str = os.getenv("CONSUMER_GROUP", "eventproc")
    consumer_name: str = os.getenv("CONSUMER_NAME", "ep-1")
    metrics_port: int = int(os.getenv("METRICS_PORT", "8003"))


def get_config() -> Config:
    return Config()
