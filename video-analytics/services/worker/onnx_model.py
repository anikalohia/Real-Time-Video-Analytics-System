import os
import urllib.request
from typing import List, Tuple

import cv2
import numpy as np
import onnxruntime as ort


class YOLOv5ONNX:
    def __init__(self, model_path="yolov5n.onnx", input_size=640, conf_threshold=0.5, nms_threshold=0.4):
        self.model_path = model_path
        self.input_size = input_size
        self.conf_threshold = conf_threshold
        self.nms_threshold = nms_threshold
        self._ensure_model()
        self.session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        # COCO classes for YOLOv5
        self.class_names = [
            "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
            "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
            "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
            "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
            "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
            "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
            "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake",
            "chair", "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop",
            "mouse", "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
            "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
            "toothbrush",
        ]

    def _ensure_model(self):
        if os.path.exists(self.model_path):
            return
        # download yolov5n.onnx if missing
        url = "https://github.com/ultralytics/yolov5/releases/download/v7.0/yolov5n.onnx"
        try:
            urllib.request.urlretrieve(url, self.model_path)
        except Exception as e:
            raise RuntimeError(f"Failed to download ONNX model from {url}: {e}") from e
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"Model not found after download: {self.model_path}")

    def letterbox(self, img: np.ndarray, new_shape: int):
        h, w = img.shape[:2]
        r = new_shape / max(h, w)
        nh, nw = int(round(h * r)), int(round(w * r))
        img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        top = (new_shape - nh) // 2
        bottom = new_shape - nh - top
        left = (new_shape - nw) // 2
        right = new_shape - nw - left
        img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))
        return img, r, left, top

    def detect(self, img: np.ndarray) -> List[Tuple[int, float, int, int, int, int]]:
        orig_h, orig_w = img.shape[:2]
        img_resized, r, pad_w, pad_h = self.letterbox(img, self.input_size)
        img_resized = img_resized.transpose(2, 0, 1).astype(np.float32) / 255.0
        blob = np.expand_dims(img_resized, axis=0)
        pred = self.session.run([self.output_name], {self.input_name: blob})[0]
        # pred shape depends on model; yolov5n onnx typically [1, 25200, 85]
        results = []
        if pred.shape[2] == 85:
            # [1, num, 85]
            pred = pred[0]
            for det in pred:
                conf = det[4]
                if conf < self.conf_threshold:
                    continue
                cls_scores = det[5:]
                cls_id = int(np.argmax(cls_scores))
                cls_conf = float(cls_scores[cls_id])
                if cls_conf < self.conf_threshold:
                    continue
                xc, yc, w, h = det[0], det[1], det[2], det[3]
                x1 = int((xc - w / 2 - pad_w) / r)
                y1 = int((yc - h / 2 - pad_h) / r)
                x2 = int((xc + w / 2 - pad_w) / r)
                y2 = int((yc + h / 2 - pad_h) / r)
                x1 = max(0, min(orig_w - 1, x1))
                y1 = max(0, min(orig_h - 1, y1))
                x2 = max(0, min(orig_w - 1, x2))
                y2 = max(0, min(orig_h - 1, y2))
                results.append((cls_id, float(conf), x1, y1, x2, y2))
        else:
            # handle other formats if needed
            pass
        # NMS
        boxes = [(r[2], r[3], r[4], r[5]) for r in results]
        confs = [r[1] for r in results]
        clss = [r[0] for r in results]
        indices = cv2.dnn.NMSBoxes(boxes, confs, self.conf_threshold, self.nms_threshold)
        out = []
        if len(indices) > 0:
            for i in indices.flatten():
                out.append((clss[i], confs[i], boxes[i][0], boxes[i][1], boxes[i][2], boxes[i][3]))
        return out
