# Architecture

System pipeline using Redis Streams:

```
[Video source / RTSP] 
        |
  [Ingestion Service] --frames--> Redis Stream: frames:{stream_id}
        |                            |
        |                   [Detection Workers] (consumer group)
        |                            |
        |                   Redis Stream: detections
        |                            |
        |                   [Event Processor]
        |                    |           |
        |             [PostgreSQL]   [Rule Engine] --> alerts
        |                    |           |
        +------------------> [API Gateway (REST + WebSocket)] --> [Dashboard]
                |
             Prometheus/Grafana
```

## Components
- **Ingestion**: Captures frames, samples, encodes JPEG, publishes to Redis Streams
- **Worker**: Runs YOLO via ONNX Runtime, publishes detections
- **Event Processor**: Dedupes, writes events, broadcasts to API/rules
- **Rule Engine**: Zone-based and count-based alerts with cooldown
- **API**: FastAPI REST + WebSocket, exposes /metrics
- **Dashboard**: Next.js with live overlays

## Flow
1. Frames published to `frames:{stream_id}` with MAXLEN
2. Workers consume via consumer group, drop stale frames
3. Detections published to `detections` stream
4. Event processor batches writes to PostgreSQL, feeds rules/API
5. Dashboard receives live data via WebSocket
6. Metrics exported to Prometheus
