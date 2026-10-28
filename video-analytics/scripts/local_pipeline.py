"""Run the pipeline locally with fakeredis + SQLite, without Docker.

This is the smoke test for environments where the Docker daemon is unavailable.
It uses the real ingestion, worker, and event-processor classes; only Redis and
PostgreSQL are replaced with in-process fakes. It is not a throughput benchmark.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (
    ROOT / 'services' / 'ingestion',
    ROOT / 'services' / 'worker',
    ROOT / 'services' / 'event-processor',
):
    sys.path.insert(0, str(path))


def make_synthetic_clip(path: Path, seconds: int = 3, fps: int = 10):
    import cv2
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*'MJPG'),
        fps,
        (640, 360),
    )
    if not writer.isOpened():
        raise SystemExit(f'could not create synthetic clip at {path}')
    frames = seconds * fps
    for i in range(frames):
        img = np.zeros((360, 640, 3), np.uint8)
        img[:] = (30, 30, 30)
        x = int(60 + (i % 60) * 8)
        cv2.rectangle(img, (x, 120), (x + 60, 260), (40, 180, 80), -1)
        cv2.putText(
            img,
            'local pipeline',
            (20, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (220, 220, 220),
            2,
        )
        writer.write(img)
    writer.release()


def ensure_clip(path: Path) -> Path:
    if path.exists() and path.stat().st_size > 0:
        return path
    fallback = path.with_name('synthetic.avi')
    make_synthetic_clip(fallback)
    print(json.dumps({'event': 'using_synthetic_clip', 'path': str(fallback)}))
    return fallback


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', choices=['mock', 'onnx', 'yolo'], default='mock')
    parser.add_argument('--seconds', type=float, default=20)
    parser.add_argument('--fps', type=int, default=5)
    parser.add_argument('--streams', type=int, default=1)
    parser.add_argument('--sample', default=str(ROOT / 'samples' / 'sample.avi'))
    parser.add_argument('--keep-db', action='store_true')
    args = parser.parse_args()

    clip = ensure_clip(Path(args.sample))
    db_path = Path(tempfile.gettempdir()) / f'va-local-{uuid.uuid4().hex}.db'
    os.environ['POSTGRES_DSN'] = f'sqlite:///{db_path}'
    os.environ['DETECTOR_BACKEND'] = args.backend
    os.environ['BATCH_SIZE'] = '10'
    os.environ['FLUSH_INTERVAL'] = '1.0'
    os.environ['EVENT_LOG_INTERVAL'] = '0'
    os.environ['STALE_THRESHOLD_MS'] = '5000'
    if args.backend == 'onnx':
        os.environ.setdefault('MODEL_PATH', str(ROOT / 'models' / 'yolov5n.onnx'))
        os.environ.setdefault(
            'MODEL_URL',
            'https://github.com/ultralytics/yolov5/releases/download/v7.0/yolov5n.onnx',
        )

    import fakeredis
    from ingestion import StreamIngestor
    from processor import EventProcessor
    from prometheus_client import REGISTRY
    from sqlalchemy import create_engine, func, select

    from models import Alert, Base, Event, Rule, Stream

    # Worker and ingestion both expose stream_fps in separate containers. In
    # this single process the default registry would reject the duplicate, so
    # drop the collectors registered by the first service before importing the
    # second. Metrics are not the subject of this local smoke test.
    for collector in list(REGISTRY._collector_to_names):
        REGISTRY.unregister(collector)
    import detector as worker_mod  # noqa: E402

    redis_client = fakeredis.FakeStrictRedis(decode_responses=True)
    engine = create_engine(os.environ['POSTGRES_DSN'])
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)

    demo_ids = []
    with Session() as session:
        for i in range(args.streams):
            sid = uuid.UUID(f'00000000-0000-0000-0000-{i + 1:012d}')
            demo_ids.append(sid)
            session.add(
                Stream(
                    id=sid,
                    name=f'local-demo-{i + 1}',
                    source_url=str(clip),
                    status='running',
                    health='reconnecting',
                    target_fps=args.fps,
                )
            )
            session.add(
                Rule(
                    stream_id=sid,
                    name='local person',
                    class_filter='person',
                    threshold_count=1,
                    cooldown_seconds=5,
                    enabled=True,
                )
            )
        session.commit()

    def update_health(stream_id: str, health: str):
        with Session() as session:
            stream = session.get(Stream, uuid.UUID(stream_id))
            if stream:
                stream.health = health
                session.commit()

    ep = EventProcessor()
    ep.redis = redis_client
    ep.ensure_consumer_group()
    workers = []
    for _ in range(1):
        worker = worker_mod.DetectionWorker()
        worker.redis = redis_client
        workers.append(worker)
    ingestors = []
    for sid in demo_ids:
        ingestor = StreamIngestor(
            str(sid),
            str(clip),
            target_fps=args.fps,
            status_cb=lambda health, sid=str(sid): update_health(sid, health),
        )
        ingestor.redis = redis_client
        ingestors.append(ingestor)

    threads = []
    for ingestor in ingestors:
        t = threading.Thread(target=ingestor.run, daemon=True)
        t.start()
        threads.append(t)
    for worker in workers:
        t = threading.Thread(target=worker.run, daemon=True)
        t.start()
        threads.append(t)
    t = threading.Thread(target=ep.run, daemon=True)
    t.start()
    threads.append(t)

    if args.backend == 'mock':
        # MockDetector intentionally emits stochastic boxes; give it a slightly
        # longer window so the e2e check is not flaky.
        time.sleep(max(args.seconds, 5))
    else:
        time.sleep(args.seconds)

    for ingestor in ingestors:
        ingestor.running = False
    for worker in workers:
        worker.running = False
    ep.running = False
    for t in threads:
        t.join(timeout=5)
    ep.flush()
    ep.webhooks.close()

    with Session() as session:
        event_count = session.scalar(select(func.count()).select_from(Event))
        alert_count = session.scalar(select(func.count()).select_from(Alert))
        stream_count = session.scalar(select(func.count()).select_from(Stream))
    frames = redis_client.xlen(f'frames:{demo_ids[0]}')
    detections = redis_client.xlen('detections')
    latest = redis_client.hgetall(f'latest:{demo_ids[0]}')
    summary = {
        'frames_in_stream': frames,
        'detections_in_stream': detections,
        'events_in_db': int(event_count or 0),
        'alerts_in_db': int(alert_count or 0),
        'streams_in_db': int(stream_count or 0),
        'latest_frame_cached': bool(latest.get('image_b64')),
        'backend': args.backend,
        'seconds': args.seconds,
    }
    print(json.dumps(summary, indent=2))
    if not args.keep_db:
        try:
            db_path.unlink(missing_ok=True)
        except PermissionError:
            pass
    return 0 if frames > 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
