import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from tracker import IoUTracker, iou  # noqa: E402


def _det(x=0.1, y=0.1, cls='person'):
    return {'class': cls, 'confidence': 0.9, 'bbox': {'x': x, 'y': y, 'w': 0.2, 'h': 0.2}}


def test_iou_identical_and_disjoint():
    a = {'x': 0.1, 'y': 0.1, 'w': 0.2, 'h': 0.2}
    assert iou(a, a) == 1.0
    assert iou(a, {'x': 0.8, 'y': 0.8, 'w': 0.1, 'h': 0.1}) == 0.0


def test_tracker_reuses_track_for_overlapping_detection():
    tracker = IoUTracker(iou_threshold=0.3)
    first = tracker.update([_det()], now=100.0)[0]
    second = tracker.update([_det(x=0.11)], now=100.1)[0]
    assert first['is_new_track'] is True
    assert second['is_new_track'] is False
    assert second['track_id'] == first['track_id']


def test_tracker_separates_classes_and_expires_ttl():
    tracker = IoUTracker(iou_threshold=0.3, ttl_seconds=1.0)
    person = tracker.update([_det()], now=100.0)[0]
    car = tracker.update([_det(cls='car')], now=100.1)[0]
    assert car['track_id'] != person['track_id']
    expired = tracker.update([_det()], now=102.0)[0]
    assert expired['is_new_track'] is True
    assert expired['track_id'] != person['track_id']


def test_tracker_marks_logged_interval():
    tracker = IoUTracker()
    det = tracker.update([_det()], now=100.0)[0]
    assert tracker.should_log(det) is True
    tracker.mark_logged(det['track_id'], now=100.0)
    next_frame = tracker.update([_det()], now=100.1)[0]
    assert tracker.should_log(next_frame, min_interval_seconds=5, now=100.2) is False
