import os
from dataclasses import dataclass


@dataclass
class Config:
    redis_host: str = os.getenv('REDIS_HOST', 'localhost')
    redis_port: int = int(os.getenv('REDIS_PORT', '6379'))
    redis_db: int = int(os.getenv('REDIS_DB', '0'))
    postgres_dsn: str = os.getenv('POSTGRES_DSN', 'postgresql://user:pass@localhost:5432/analytics')
    batch_size: int = int(os.getenv('BATCH_SIZE', '10'))
    flush_interval: float = float(os.getenv('FLUSH_INTERVAL', '1.0'))
    db_buffer_max: int = int(os.getenv('DB_BUFFER_MAX', '2000'))
    event_log_interval: float = float(os.getenv('EVENT_LOG_INTERVAL', '0'))
    track_iou_threshold: float = float(os.getenv('TRACK_IOU_THRESHOLD', '0.3'))
    track_ttl_seconds: float = float(os.getenv('TRACK_TTL_SECONDS', '5'))
    consumer_group: str = os.getenv('CONSUMER_GROUP', 'eventproc')
    consumer_name: str = os.getenv('CONSUMER_NAME', 'ep-1')
    metrics_port: int = int(os.getenv('METRICS_PORT', '8003'))
    webhook_timeout: float = float(os.getenv('WEBHOOK_TIMEOUT', '5'))
    webhook_max_attempts: int = int(os.getenv('WEBHOOK_MAX_ATTEMPTS', '3'))
    max_delivery_attempts: int = int(os.getenv('MAX_DELIVERY_ATTEMPTS', '3'))


def get_config() -> Config:
    return Config()
