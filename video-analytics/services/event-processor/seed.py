"""Idempotently seed the demo stream and a starter rule.

This keeps `docker compose up` a true one-command demo: the ingestion manager
finds the running demo stream and starts publishing frames without any API
calls. Existing rows are never overwritten, so a user can stop the demo stream
and it will stay stopped across restarts.
"""

import os
import sys
import uuid

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from models import Rule, Stream

DEMO_STREAM_ID = uuid.UUID('00000000-0000-0000-0000-000000000001')
DEMO_RULE_ID = uuid.UUID('00000000-0000-0000-0000-000000000002')


def main() -> int:
    dsn = os.getenv('POSTGRES_DSN', 'postgresql://user:pass@localhost:5432/analytics')
    source_url = os.getenv('DEMO_SOURCE_URL', 'rtsp://mediamtx:8554/demo')
    name = os.getenv('DEMO_STREAM_NAME', 'demo')
    fps = int(os.getenv('DEMO_TARGET_FPS', '10'))

    engine = create_engine(dsn, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    try:
        with Session() as session:
            stream = session.get(Stream, DEMO_STREAM_ID)
            if stream is None:
                session.add(
                    Stream(
                        id=DEMO_STREAM_ID,
                        name=name,
                        source_url=source_url,
                        status='running',
                        health='reconnecting',
                        target_fps=fps,
                    )
                )
                print(f'[seed] inserted demo stream {name} -> {source_url}')
            else:
                print(f'[seed] demo stream already exists (status={stream.status})')

            rule = session.get(Rule, DEMO_RULE_ID)
            if rule is None:
                session.add(
                    Rule(
                        id=DEMO_RULE_ID,
                        stream_id=DEMO_STREAM_ID,
                        name='Person detected',
                        class_filter='person',
                        zone_polygon=None,
                        threshold_count=1,
                        dwell_seconds=0,
                        cooldown_seconds=30,
                        enabled=True,
                    )
                )
                print("[seed] inserted starter rule 'Person detected'")
            session.commit()
    except OperationalError as exc:
        print(f'[seed] database not ready: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
