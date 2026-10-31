"""Stream manager: polls the database for streams marked 'running' and
starts/stops an ingestor thread per stream. This makes the API/UI
start/stop controls effective without restarting containers.
"""

import json
import os
import threading
import time

from ingest_config import get_config
from ingestion import StreamIngestor
from sqlalchemy import create_engine, text

cfg = get_config()
postgres_dsn = os.getenv('POSTGRES_DSN', 'postgresql://user:pass@localhost:5432/analytics')


def log_event(**fields):
    print(json.dumps({'service': 'ingestion-manager', **fields}, default=str), flush=True)


class StreamManager:
    def __init__(self):
        self.engine = create_engine(postgres_dsn, pool_pre_ping=True)
        self.ingestors: dict[str, StreamIngestor] = {}
        self.threads: dict[str, threading.Thread] = {}
        self.running = True

    def fetch_running(self) -> list[tuple[str, str, int | None]] | None:
        """Return running streams, or None when the database is unavailable.

        None is deliberately distinct from an empty list: an empty list means
        every stream is stopped, while None means we could not read the desired
        state and must keep the current ingestors running.
        """
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        'SELECT id, source_url, target_fps FROM streams ' "WHERE status = 'running'"
                    )
                ).fetchall()
            return [(str(r[0]), r[1], r[2]) for r in rows]
        except Exception as exc:
            log_event(event='db_unavailable', error=str(exc))
            return None

    def update_health(self, sid: str, health: str):
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text('UPDATE streams SET health = :health WHERE id = :sid'),
                    {'health': health, 'sid': sid},
                )
        except Exception:
            pass

    def clear_frame_cache(self, sid: str):
        try:
            import redis

            r = redis.Redis(
                host=cfg.redis_host,
                port=cfg.redis_port,
                db=cfg.redis_db,
                decode_responses=True,
            )
            r.delete(f'latest:{sid}')
        except Exception:
            pass

    def start_stream(self, sid: str, source_url: str, target_fps: int):
        ing = StreamIngestor(
            sid,
            source_url,
            target_fps=target_fps or cfg.max_fps,
            status_cb=lambda health, stream_id=sid: self.update_health(stream_id, health),
        )
        self.ingestors[sid] = ing
        t = threading.Thread(target=ing.run, name=f'ingest-{sid}', daemon=True)
        self.threads[sid] = t
        self.update_health(sid, 'reconnecting')
        t.start()
        log_event(event='stream_started', stream_id=sid, source=source_url)

    def stop_stream(self, sid: str):
        ing = self.ingestors.pop(sid, None)
        if ing:
            ing.stop()
        self.threads.pop(sid, None)
        self.clear_frame_cache(sid)
        self.update_health(sid, 'stopped')
        log_event(event='stream_stopped', stream_id=sid)

    def reconcile(self, running: list[tuple[str, str, int | None]]):
        running_ids = {sid for sid, _, _ in running}
        for sid in list(self.ingestors.keys()):
            if sid not in running_ids:
                self.stop_stream(sid)
        for sid, source_url, fps in running:
            if sid not in self.ingestors:
                self.start_stream(sid, source_url, fps)

    def run(self):
        while self.running:
            running = self.fetch_running()
            if running is not None:
                self.reconcile(running)
            time.sleep(cfg.manager_poll_seconds)

    def shutdown(self):
        self.running = False
        for sid in list(self.ingestors.keys()):
            self.stop_stream(sid)
