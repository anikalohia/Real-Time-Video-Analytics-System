# Benchmarks

The load-test harness is `load_test.py`. It publishes synthetic frames and
reports end-to-end latency, processed/stale counts, and p50/p95/p99.

## Results

- [2026-10-31 CPU-only run](results/2026-10-31-cpu-only.md): 2 and 4 stream
  scenarios, YOLOv5n inference, Docker Compose on Windows/WSL2.

Run inside the Compose network so the numbers do not include host-network
overhead:

```bash
docker run --rm --network video-analytics_default \
  --entrypoint python \
  -v "$PWD/benchmarks:/bench:ro" \
  video-analytics-worker \
  /bench/load_test.py --redis-host redis --streams 4 --seconds 60 --fps 10
```

Adjust the network name if `COMPOSE_PROJECT_NAME` is set.
