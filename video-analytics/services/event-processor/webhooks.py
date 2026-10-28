"""Async webhook delivery with bounded retries for alert rules."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx

try:
    from prometheus_client import Counter
except ImportError:  # pragma: no cover
    Counter = None

if Counter:
    webhook_deliveries = Counter('webhook_deliveries_total', 'Webhook deliveries', ['status'])
else:  # pragma: no cover
    webhook_deliveries = None


def valid_webhook_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    return parsed.scheme in {'http', 'https'} and bool(parsed.netloc)


class WebhookDispatcher:
    def __init__(
        self,
        on_result: Callable[[str, bool], None],
        timeout: float = 5.0,
        max_attempts: int = 3,
    ):
        self.on_result = on_result
        self.timeout = timeout
        self.max_attempts = max_attempts
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='webhook')
        self._client = httpx.Client(timeout=timeout)
        self._lock = threading.Lock()
        self._closed = False

    def submit(self, alert_id: str, url: str, payload: dict):
        if not valid_webhook_url(url):
            self.on_result(alert_id, False)
            return
        if self._closed:
            return
        self._pool.submit(self._deliver, alert_id, url, payload)

    def _deliver(self, alert_id: str, url: str, payload: dict):
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._client.post(url, json=payload)
                if 200 <= response.status_code < 300:
                    if webhook_deliveries:
                        webhook_deliveries.labels(status='success').inc()
                    self.on_result(alert_id, True)
                    return
            except Exception:
                pass
            if attempt < self.max_attempts:
                time.sleep(min(2**attempt * 0.25, 2.0))
        if webhook_deliveries:
            webhook_deliveries.labels(status='failed').inc()
        self.on_result(alert_id, False)

    def close(self):
        self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._client.close()


def payload_json(payload: dict) -> str:
    return json.dumps(payload, default=str)
