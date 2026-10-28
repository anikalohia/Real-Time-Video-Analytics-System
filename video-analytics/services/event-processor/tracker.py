"""Lightweight IoU tracker used to deduplicate detections into objects.

It is intentionally small (no Kalman filter): a class-aware greedy IoU match
with a short track TTL is enough to stop logging the same person on every
frame while keeping the event stream useful.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field


def iou(a: dict, b: dict) -> float:
    ax1, ay1 = a.get('x', 0.0), a.get('y', 0.0)
    ax2, ay2 = ax1 + a.get('w', 0.0), ay1 + a.get('h', 0.0)
    bx1, by1 = b.get('x', 0.0), b.get('y', 0.0)
    bx2, by2 = bx1 + b.get('w', 0.0), by1 + b.get('h', 0.0)
    inter_w = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    inter_h = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = inter_w * inter_h
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


@dataclass
class Track:
    track_id: str
    class_name: str
    bbox: dict
    first_seen: float
    last_seen: float
    last_logged: float = field(default=0.0)


class IoUTracker:
    def __init__(self, iou_threshold: float = 0.3, ttl_seconds: float = 5.0):
        self.iou_threshold = iou_threshold
        self.ttl_seconds = ttl_seconds
        self._tracks: list[Track] = []
        self._counter = itertools.count(1)

    def _new_id(self) -> str:
        return f't{next(self._counter)}'

    def update(self, detections: list[dict], now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        self._tracks = [t for t in self._tracks if now - t.last_seen <= self.ttl_seconds]

        pairs = []
        for det_index, det in enumerate(detections):
            if not det.get('bbox'):
                continue
            for track_index, track in enumerate(self._tracks):
                if track.class_name != det.get('class'):
                    continue
                score = iou(track.bbox, det['bbox'])
                if score >= self.iou_threshold:
                    pairs.append((score, det_index, track_index))
        pairs.sort(reverse=True)

        assigned_dets: set[int] = set()
        assigned_tracks: set[int] = set()
        result = [dict(det) for det in detections]
        for _score, det_index, track_index in pairs:
            if det_index in assigned_dets or track_index in assigned_tracks:
                continue
            track = self._tracks[track_index]
            det = result[det_index]
            track.bbox = det['bbox']
            track.last_seen = now
            det['track_id'] = track.track_id
            det['track_first_seen'] = track.first_seen
            det['is_new_track'] = False
            assigned_dets.add(det_index)
            assigned_tracks.add(track_index)

        for det_index, det in enumerate(result):
            if det_index in assigned_dets or not det.get('bbox'):
                continue
            track = Track(
                track_id=self._new_id(),
                class_name=det.get('class', 'unknown'),
                bbox=det['bbox'],
                first_seen=now,
                last_seen=now,
            )
            self._tracks.append(track)
            det['track_id'] = track.track_id
            det['track_first_seen'] = track.first_seen
            det['is_new_track'] = True

        return result

    def mark_logged(self, track_id: str, now: float | None = None):
        now = time.time() if now is None else now
        for track in self._tracks:
            if track.track_id == track_id:
                track.last_logged = now
                return

    def should_log(
        self,
        det: dict,
        min_interval_seconds: float = 0.0,
        now: float | None = None,
    ) -> bool:
        if det.get('is_new_track'):
            return True
        if min_interval_seconds <= 0:
            return False
        now = time.time() if now is None else now
        for track in self._tracks:
            if track.track_id == det.get('track_id'):
                return (now - track.last_logged) >= min_interval_seconds
        return False

    def active_count(self) -> int:
        return len(self._tracks)
