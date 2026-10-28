"""Rule engine: zone membership, count thresholds, dwell time, cooldown."""

import time
from typing import Any


def point_in_polygon(x: float, y: float, polygon: list[list[float]] | None) -> bool:
    """Ray casting algorithm. x,y normalized [0,1]."""
    if not polygon or len(polygon) < 3:
        return False
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi):
            inside = not inside
        j = i
    return inside


def center(bbox: dict[str, float]) -> tuple[float, float]:
    return (bbox['x'] + bbox['w'] / 2.0, bbox['y'] + bbox['h'] / 2.0)


def _object_key(det: dict[str, Any]) -> str:
    if det.get('track_id'):
        return f"track:{det['track_id']}"
    bbox = det.get('bbox') or {}
    cx, cy = center(bbox) if bbox else (0.0, 0.0)
    return f"{det.get('class')}:{round(cx, 2)}:{round(cy, 2)}"


class RuleEngine:
    def __init__(self):
        self._last_fired: dict[str, float] = {}
        # state is keyed by (stream_id, rule_id) -> object key -> timings
        self._dwell: dict[tuple[str, str], dict[str, dict[str, float]]] = {}

    def _cooldown_ok(self, rule: dict[str, Any], now: float) -> bool:
        rid = str(rule['id'])
        return now - self._last_fired.get(rid, 0.0) >= float(rule.get('cooldown_seconds', 60))

    def evaluate(
        self,
        detections: list[dict[str, Any]],
        rules: list[dict[str, Any]],
        stream_id: str,
        now: float | None = None,
    ) -> list[dict[str, Any]]:
        """Return alerts for the given stream detections."""
        now = time.time() if now is None else now
        alerts: list[dict[str, Any]] = []
        stream_rules = [
            r for r in rules if str(r.get('stream_id')) == str(stream_id) and r.get('enabled', True)
        ]

        for rule in stream_rules:
            cls_filter = rule.get('class_filter')
            zone = rule.get('zone_polygon')
            threshold = max(1, int(rule.get('threshold_count', 1)))
            dwell = float(rule.get('dwell_seconds', 0) or 0)
            rid = str(rule['id'])
            state_key = (str(stream_id), rid)

            matched = []
            for det in detections:
                if cls_filter and det.get('class') != cls_filter:
                    continue
                bbox = det.get('bbox')
                if not bbox:
                    continue
                if zone:
                    cx, cy = center(bbox)
                    if not point_in_polygon(cx, cy, zone):
                        continue
                matched.append(det)

            # Count unique objects, not raw detections.
            unique: dict[str, dict[str, Any]] = {}
            for det in matched:
                unique.setdefault(_object_key(det), det)
            count = len(unique)
            if count < threshold:
                continue

            if dwell > 0:
                dwell_state = self._dwell.setdefault(state_key, {})
                gap = max(2.0, dwell * 2.0)
                sustained = []
                for key in unique:
                    entry = dwell_state.get(key)
                    if entry is None or now - entry['last_seen'] > gap:
                        dwell_state[key] = {'first_seen': now, 'last_seen': now}
                    else:
                        entry['last_seen'] = now
                    if now - dwell_state[key]['first_seen'] >= dwell:
                        sustained.append(key)
                # Prune objects that have not been seen for a while.
                for key in list(dwell_state):
                    if now - dwell_state[key]['last_seen'] > gap:
                        dwell_state.pop(key, None)
                if not sustained:
                    continue
                for key in sustained:
                    dwell_state.pop(key, None)

            if not self._cooldown_ok(rule, now):
                continue
            self._last_fired[rid] = now
            alerts.append(
                {
                    'rule_id': rule['id'],
                    'rule_name': rule.get('name'),
                    'stream_id': stream_id,
                    'webhook_url': rule.get('webhook_url'),
                    'ts': now,
                    'payload': {
                        'message': rule.get('name', 'Rule fired'),
                        'class': cls_filter,
                        'count': count,
                        'threshold': threshold,
                        'zone': bool(zone),
                        'detections': matched[:10],
                    },
                }
            )
        return alerts
