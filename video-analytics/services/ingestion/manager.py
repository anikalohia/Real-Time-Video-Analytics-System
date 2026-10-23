"""Stream manager: polls the database for streams marked 'running' and
starts/stops an ingestor thread per stream. This makes the API/UI
start/stop controls effective without restarting containers.
"""
import os
import threading
import time
from typing import Dict

from sqlalchemy import create_engine, text

from ingest_config import get_config
from ingestion import StreamIngestor

cfg = get_config()
postgres_dsn = os.getenv("POSTGRES_DSN", "postgresql://user:pass@localhost:5432/analytics")


class StreamManager:
    def __init__(self):
        self.engine = create_engine(postgres_dsn, pool_pre_ping=True)
        self.ingestors: Dict[str, StreamIngestor] = {}
        self.threads: Dict[str, threading.Thread] = {}
        self.running = True

    def fetch_running(self):
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT id, source_url, target_fps FROM streams WHERE status = 'running'")
                ).fetchall()
            return [(str(r[0]), r[1], r[2]) for r in rows]
        except Exception:
            return []

    def start_stream(self, sid: str, source_url: str, target_fps: int):
        ing = StreamIngestor(sid, source_url)
        ing.target_fps = target_fps or cfg.max_fps
        self.ingestors[sid] = ing
        t = threading.Thread(target=ing.run, daemon=True)
        self.threads[sid] = t
        t.start()
        print(f"[manager] started stream {sid} <- {source_url}")

    def stop_stream(self, sid: str):
        ing = self.ingestors.pop(sid, None)
        if ing:
            ing.running = False
            if ing.cap:
                ing.cap.release()
        self.threads.pop(sid, None)
        print(f"[manager] stopped stream {sid}")

    def run(self):
        # ensure table/columns exist by waiting for event-processor (or api) to create schema
        while self.running:
            running = self.fetch_running()
            running_ids = {sid for sid, _, _ in running}
            for sid in list(self.ingestors.keys()):
                if sid not in running_ids:
                    self.stop_stream(sid)
            for sid, source_url, fps in running:
                if sid not in self.ingestors:
                    self.start_stream(sid, source_url, fps)
            time.sleep(3)
