import os
from dataclasses import dataclass


@dataclass
class Config:
    redis_host: str = os.getenv('REDIS_HOST', 'localhost')
    redis_port: int = int(os.getenv('REDIS_PORT', '6379'))
    redis_db: int = int(os.getenv('REDIS_DB', '0'))
    detector_backend: str = os.getenv('DETECTOR_BACKEND', 'onnx')  # onnx | mock | yolo
    model_path: str = os.getenv('MODEL_PATH', 'yolov5n.onnx')
    model_url: str = os.getenv(
        'MODEL_URL',
        'https://github.com/ultralytics/yolov5/releases/download/v7.0/yolov5n.onnx',
    )
    input_size: int = int(os.getenv('INPUT_SIZE', '640'))
    confidence_threshold: float = float(os.getenv('CONF_THRESHOLD', '0.5'))
    nms_threshold: float = float(os.getenv('NMS_THRESHOLD', '0.4'))
    batch_size: int = int(os.getenv('BATCH_SIZE', '1'))
    stale_threshold_ms: int = int(os.getenv('STALE_THRESHOLD_MS', '300'))
    max_delivery_attempts: int = int(os.getenv('MAX_DELIVERY_ATTEMPTS', '3'))
    reclaim_min_idle_ms: int = int(os.getenv('RECLAIM_MIN_IDLE_MS', '30000'))
    consumer_group: str = os.getenv('CONSUMER_GROUP', 'workers')
    consumer_name: str = os.getenv('CONSUMER_NAME', '')
    dead_letter_stream: str = os.getenv('DEAD_LETTER_STREAM', 'dead-letter')
    metrics_port: int = int(os.getenv('METRICS_PORT', '8002'))


def get_config() -> Config:
    return Config()
