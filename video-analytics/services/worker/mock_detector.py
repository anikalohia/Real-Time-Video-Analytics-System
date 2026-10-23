"""Deterministic mock detector for local development and tests.

Emits a couple of pseudo-detections per frame so the full pipeline
(Redis -> event processor -> DB -> API -> dashboard) can be exercised
without ONNX Runtime or a real model.
"""
import random
from typing import List, Tuple

import numpy as np


class MockDetector:
    class_names = ["person", "car", "bicycle", "dog", "truck"]

    def __init__(self, *args, **kwargs):
        pass

    def detect(self, img: np.ndarray) -> List[Tuple[int, float, int, int, int, int]]:
        h, w = img.shape[:2]
        results = []
        n = random.randint(0, 3)
        for _ in range(n):
            cls_id = random.randint(0, len(self.class_names) - 1)
            x1 = random.randint(0, max(0, w - 60))
            y1 = random.randint(0, max(0, h - 60))
            bw = random.randint(30, 120)
            bh = random.randint(40, 160)
            x2 = min(w - 1, x1 + bw)
            y2 = min(h - 1, y1 + bh)
            conf = round(random.uniform(0.5, 0.95), 2)
            results.append((cls_id, conf, x1, y1, x2, y2))
        return results
