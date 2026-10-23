"""Load test: publish synthetic frames to Redis and measure end-to-end
detection latency (frame publish -> detection published).

Usage:
    python benchmarks/load_test.py --streams 4 --seconds 60 --fps 10
"""
import argparse
import base64
import json
import os
import statistics
import time
import uuid

import cv2
import numpy as np
import redis


def make_jpeg():
    img = np.random.randint(0, 255, (360, 640, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--streams", type=int, default=4)
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "localhost"))
    ap.add_argument("--redis-port", type=int, default=int(os.getenv("REDIS_PORT", "6379")))
    args = ap.parse_args()

    r = redis.Redis(host=args.redis_host, port=args.redis_port, decode_responses=True)
    r.ping()

    stream_ids = [f"bench-{uuid.uuid4().hex[:6]}" for _ in range(args.streams)]
    sent = {}  # frame_id -> publish ts
    published = 0
    interval = 1.0 / args.fps
    end = time.time() + args.seconds
    jpeg = make_jpeg()

    # reader thread measures latency from detections stream
    import threading

    latencies = []
    stop = threading.Event()

    def reader():
        last_id = "$"
        while not stop.is_set():
            try:
                res = r.xread({"detections": last_id}, count=100, block=1000)
                if not res:
                    continue
                for _, msgs in res:
                    for msg_id, fields in msgs:
                        last_id = msg_id
                        for d in json.loads(fields.get("detections", "[]")):
                            key = (d["stream_id"], d.get("frame_id"))
                            if key in sent:
                                latencies.append((time.time() - sent[key]) * 1000)
            except Exception:
                time.sleep(0.5)

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    print(f"Publishing {args.streams} streams at {args.fps} FPS for {args.seconds}s...")
    frame_id = 0
    while time.time() < end:
        for sid in stream_ids:
            frame_id += 1
            ts = time.time()
            sent[(sid, frame_id)] = ts
            meta = {"stream_id": sid, "frame_id": frame_id, "ts": ts, "capture_ts": ts,
                    "width": 640, "height": 360, "format": "jpeg"}
            r.xadd(f"frames:{sid}", {"metadata": json.dumps(meta), "image_b64": jpeg},
                   maxlen=1000, approximate=True)
            published += 1
        time.sleep(interval)

    print("Waiting for in-flight detections...")
    time.sleep(5)
    stop.set()

    if latencies:
        latencies.sort()
        p = lambda q: latencies[min(len(latencies) - 1, int(len(latencies) * q))]
        print(f"published frames: {published}")
        print(f"latency samples:  {len(latencies)}")
        print(f"p50: {p(0.5):.1f} ms")
        print(f"p95: {p(0.95):.1f} ms")
        print(f"p99: {p(0.99):.1f} ms")
        print(f"mean: {statistics.mean(latencies):.1f} ms")
    else:
        print("No latency samples collected. Is the worker running?")


if __name__ == "__main__":
    main()
