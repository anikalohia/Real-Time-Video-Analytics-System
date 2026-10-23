"""Rule engine: zone membership, count thresholds, dwell time, cooldown."""
import time
from typing import Any, Dict, List, Tuple


def point_in_polygon(x: float, y: float, polygon: List[List[float]]) -> bool:
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


def center(bbox: Dict[str, float]) -> Tuple[float, float]:
    return (bbox["x"] + bbox["w"] / 2.0, bbox["y"] + bbox["h"] / 2.0)


class RuleEngine:
    def __init__(self):
        self._last_fired: Dict[str, float] = {}
        # dwell tracking: rule_id -> {object track key: first_seen_ts}
        self._dwell: Dict[str, Dict[str, float]] = {}

    def _cooldown_ok(self, rule: Dict[str, Any]) -> bool:
        rid = str(rule["id"])
        now = time.time()
        last = self._last_fired.get(rid, 0.0)
        if now - last >= rule.get("cooldown_seconds", 60):
            self._last_fired[rid] = now
            return True
        return False

    def evaluate(self, detections: List[Dict[str, Any]], rules: List[Dict[str, Any]],
                 stream_id: str) -> List[Dict[str, Any]]:
        """Return list of alerts for the given stream detections."""
        alerts: List[Dict[str, Any]] = []
        stream_rules = [r for r in rules if str(r.get("stream_id")) == str(stream_id) and r.get("enabled", True)]

        for det in detections:
            # filter by class if rule requires
            pass

        for rule in stream_rules:
            cls_filter = rule.get("class_filter")
            zone = rule.get("zone_polygon")
            threshold = rule.get("threshold_count", 1)
            dwell = rule.get("dwell_seconds", 0)
            rid = str(rule["id"])

            matched = []
            for det in detections:
                if cls_filter and det["class"] != cls_filter:
                    continue
                if zone:
                    cx, cy = center(det["bbox"])
                    if not point_in_polygon(cx, cy, zone):
                        continue
                matched.append(det)

            count = len(matched)
            if count < threshold:
                continue

            # dwell logic
            if dwell and dwell > 0:
                now = time.time()
                # use class as pseudo track key if no track id
                keys = set()
                for d in matched:
                    keys.add(str(d.get("track_id") or d["class"]))
                # require any key to have persisted > dwell
                fired = False
                for k in keys:
                    first = self._dwell.setdefault(rid, {}).setdefault(k, now)
                    if now - first >= dwell:
                        fired = True
                if not fired:
                    continue
                # reset dwell for this rule after firing
                self._dwell[rid] = {}

            if self._cooldown_ok(rule):
                alerts.append({
                    "rule_id": rule["id"],
                    "rule_name": rule.get("name"),
                    "stream_id": stream_id,
                    "ts": time.time(),
                    "payload": {
                        "message": rule.get("name", "Rule fired"),
                        "class": cls_filter,
                        "count": count,
                        "threshold": threshold,
                        "detections": matched[:10],
                    },
                })
        return alerts
