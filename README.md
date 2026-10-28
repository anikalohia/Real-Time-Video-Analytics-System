# Real-Time Video Analytics Platform

The implementation lives in [`video-analytics/`](video-analytics/).

- Product/technical requirements: [`PRD and TRD Real-Time Video Analytics Platform.md`](PRD%20and%20TRD%20Real-Time%20Video%20Analytics%20Platform.md)
- Setup, API, metrics, and testing: [`video-analytics/README.md`](video-analytics/README.md)
- Architecture: [`video-analytics/docs/architecture.md`](video-analytics/docs/architecture.md)
- Design decisions: [`video-analytics/docs/design-decisions.md`](video-analytics/docs/design-decisions.md)
- Verification status and limitations: [`video-analytics/docs/STATUS.md`](video-analytics/docs/STATUS.md)

Quick start (requires a working Docker daemon):

```bash
cd video-analytics
docker compose up --build
```

Dashboard: http://localhost:3000  
API docs: http://localhost:8000/docs  
Grafana: http://localhost:3001
