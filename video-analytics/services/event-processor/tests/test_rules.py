import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rules import RuleEngine, center, point_in_polygon


def test_point_in_polygon_inside():
    square = [[0, 0], [1, 0], [1, 1], [0, 1]]
    assert point_in_polygon(0.5, 0.5, square) is True


def test_point_in_polygon_outside():
    square = [[0, 0], [0.4, 0], [0.4, 0.4], [0, 0.4]]
    assert point_in_polygon(0.9, 0.9, square) is False


def test_point_in_polygon_degenerate():
    assert point_in_polygon(0.5, 0.5, [[0, 0], [1, 1]]) is False
    assert point_in_polygon(0.5, 0.5, None) is False


def test_center():
    cx, cy = center({"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.4})
    assert abs(cx - 0.2) < 1e-9
    assert abs(cy - 0.4) < 1e-9


def _det(cls="person", x=0.4, y=0.4):
    return {"class": cls, "confidence": 0.9, "bbox": {"x": x, "y": y, "w": 0.1, "h": 0.1}}


def test_rule_count_threshold():
    eng = RuleEngine()
    rule = {
        "id": "r1", "stream_id": "s1", "name": "crowd",
        "class_filter": "person", "zone_polygon": None,
        "threshold_count": 2, "dwell_seconds": 0,
        "cooldown_seconds": 0, "enabled": True,
    }
    alerts = eng.evaluate([_det(), _det(x=0.6)], [rule], "s1")
    assert len(alerts) == 1
    assert alerts[0]["payload"]["count"] == 2


def test_rule_below_threshold():
    eng = RuleEngine()
    rule = {"id": "r2", "stream_id": "s1", "name": "crowd", "class_filter": "person",
            "zone_polygon": None, "threshold_count": 5, "dwell_seconds": 0,
            "cooldown_seconds": 0, "enabled": True}
    assert eng.evaluate([_det()], [rule], "s1") == []


def test_rule_zone_filter():
    eng = RuleEngine()
    rule = {"id": "r3", "stream_id": "s1", "name": "zone", "class_filter": "person",
            "zone_polygon": [[0, 0], [0.3, 0], [0.3, 0.3], [0, 0.3]],
            "threshold_count": 1, "dwell_seconds": 0, "cooldown_seconds": 0, "enabled": True}
    # detection at 0.4,0.4 center 0.45 -> outside zone
    assert eng.evaluate([_det()], [rule], "s1") == []
    # detection at 0.1,0.1 -> inside
    assert len(eng.evaluate([_det(x=0.1, y=0.1)], [rule], "s1")) == 1


def test_rule_cooldown():
    eng = RuleEngine()
    rule = {"id": "r4", "stream_id": "s1", "name": "c", "class_filter": "person",
            "zone_polygon": None, "threshold_count": 1, "dwell_seconds": 0,
            "cooldown_seconds": 60, "enabled": True}
    assert len(eng.evaluate([_det()], [rule], "s1")) == 1
    # second immediate fire suppressed by cooldown
    assert eng.evaluate([_det()], [rule], "s1") == []


def test_rule_disabled():
    eng = RuleEngine()
    rule = {"id": "r5", "stream_id": "s1", "name": "c", "class_filter": None,
            "zone_polygon": None, "threshold_count": 1, "dwell_seconds": 0,
            "cooldown_seconds": 0, "enabled": False}
    assert eng.evaluate([_det()], [rule], "s1") == []
