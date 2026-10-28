import os
from dataclasses import dataclass


@dataclass
class Config:
    redis_host: str = os.getenv('REDIS_HOST', 'localhost')
    redis_port: int = int(os.getenv('REDIS_PORT', '6379'))
    redis_db: int = int(os.getenv('REDIS_DB', '0'))
    postgres_dsn: str = os.getenv('POSTGRES_DSN', 'postgresql://user:pass@localhost:5432/analytics')
    jwt_secret: str = os.getenv('JWT_SECRET', 'dev-secret-change-me')
    jwt_alg: str = os.getenv('JWT_ALG', 'HS256')
    jwt_expires_minutes: int = int(os.getenv('JWT_EXPIRES_MINUTES', '15'))
    metrics_port: int = int(os.getenv('METRICS_PORT', '8004'))
    api_host: str = os.getenv('API_HOST', '0.0.0.0')
    api_port: int = int(os.getenv('API_PORT', '8000'))
    cors_origins: str = os.getenv('CORS_ORIGINS', 'http://localhost:3000')
    rate_limit_per_minute: int = int(os.getenv('RATE_LIMIT_PER_MINUTE', '600'))
    allow_private_hosts: str = os.getenv('ALLOW_PRIVATE_HOSTS', '')
    disable_subscriber: bool = os.getenv('DISABLE_SUBSCRIBER', '0') == '1'


def get_config() -> Config:
    return Config()
