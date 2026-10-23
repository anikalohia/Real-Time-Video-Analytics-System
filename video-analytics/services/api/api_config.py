import os
from dataclasses import dataclass


@dataclass
class Config:
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_db: int = int(os.getenv("REDIS_DB", "0"))
    postgres_dsn: str = os.getenv("POSTGRES_DSN", "postgresql://user:pass@localhost:5432/analytics")
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-secret-change-me")
    jwt_alg: str = os.getenv("JWT_ALG", "HS256")
    metrics_port: int = int(os.getenv("METRICS_PORT", "8004"))
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("API_PORT", "8000"))


def get_config() -> Config:
    return Config()
