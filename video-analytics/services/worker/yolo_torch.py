"""Detector backed by Ultralytics YOLO (PyTorch).

Optional backend used when DETECTOR_BACKEND=yolo. Requires the
ultralytics and torch packages to be installed and working.
"""
from typing import List, Tuple

import numpy as np


class YOLOTorchDetector:
    def __init__(self, model_path="yolov5n.onnx", input_size=640, conf_threshold=0.5,
                 nms_threshold=0.4, weights="yolov8n.pt"):
        from ultralytics import YOLO

        self.model = YOLO(weights)
        self.conf = conf_threshold
        self.iou = nms_threshold
        self.input_size = input_size
        self.class_names = [self.model.names[i] for i in sorted(self.model.names)]

    def detect(self, img: np.ndarray) -> List[Tuple[int, float, int, int, int, int]]:
        results = self.model.predict(img, conf=self.conf, iou=self.iou, imgsz=self.input_size, verbose=False)
        out = []
        for r in results:
            for b in r.boxes:
                x1, y1, x2, y2 = b.xyxy[0].tolist()
                cls_id = int(b.cls[0].item())
                conf = float(b.conf[0].item())
                out.append((cls_id, conf, int(x1), int(y1), int(x2), int(y2)))
        return out
