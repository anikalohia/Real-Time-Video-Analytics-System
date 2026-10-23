# Design Decisions

- **Redis Streams over Kafka**: Simpler for local dev, consumer groups, bounded streams with MAXLEN. Good for 4-stream demo.
- **Client-side overlays**: Dashboard draws overlays from detection JSON (saves bandwidth vs sending full annotated frames).
- **ONNX Runtime**: Portable CPU/GPU, enables phase 2 optimizations.
- **YOLO nano**: Speed/accuracy balance on CPU.
- **PostgreSQL**: Relational queries, time-range filters, indexes.
- **WebSocket**: Simple real-time updates.
- **Docker Compose**: One-command startup.
- **Frame dropping with backpressure**: Keep latency bounded under overload.
- **Auto-reconnect with backoff**: Handle stream failures gracefully.
- **Stale frame skipping**: Drop frames older than threshold before inference.
- **XAUTOCLAIM**: Recover from crashed workers.
