import os
import tempfile
import urllib.request

import cv2
import numpy as np
import onnxruntime as ort

COCO_CLASSES = [
    'person',
    'bicycle',
    'car',
    'motorcycle',
    'airplane',
    'bus',
    'train',
    'truck',
    'boat',
    'traffic light',
    'fire hydrant',
    'stop sign',
    'parking meter',
    'bench',
    'bird',
    'cat',
    'dog',
    'horse',
    'sheep',
    'cow',
    'elephant',
    'bear',
    'zebra',
    'giraffe',
    'backpack',
    'umbrella',
    'handbag',
    'tie',
    'suitcase',
    'frisbee',
    'skis',
    'snowboard',
    'sports ball',
    'kite',
    'baseball bat',
    'baseball glove',
    'skateboard',
    'surfboard',
    'tennis racket',
    'bottle',
    'wine glass',
    'cup',
    'fork',
    'knife',
    'spoon',
    'bowl',
    'banana',
    'apple',
    'sandwich',
    'orange',
    'broccoli',
    'carrot',
    'hot dog',
    'pizza',
    'donut',
    'cake',
    'chair',
    'couch',
    'potted plant',
    'bed',
    'dining table',
    'toilet',
    'tv',
    'laptop',
    'mouse',
    'remote',
    'keyboard',
    'cell phone',
    'microwave',
    'oven',
    'toaster',
    'sink',
    'refrigerator',
    'book',
    'clock',
    'vase',
    'scissors',
    'teddy bear',
    'hair drier',
    'toothbrush',
]


class YOLOv5ONNX:
    def __init__(
        self,
        model_path='yolov5n.onnx',
        model_url='https://github.com/ultralytics/yolov5/releases/download/v7.0/yolov5n.onnx',
        input_size=640,
        conf_threshold=0.5,
        nms_threshold=0.4,
        **_kwargs,
    ):
        self.model_path = model_path
        self.model_url = model_url
        self.input_size = int(input_size)
        self.conf_threshold = float(conf_threshold)
        self.nms_threshold = float(nms_threshold)
        self.class_names = COCO_CLASSES
        self._ensure_model()
        self.session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
        input_meta = self.session.get_inputs()[0]
        self.input_name = input_meta.name
        self.input_dtype = np.float16 if 'float16' in input_meta.type else np.float32
        self.output_name = self.session.get_outputs()[0].name

    def _ensure_model(self):
        if os.path.exists(self.model_path):
            return
        directory = os.path.dirname(os.path.abspath(self.model_path))
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(suffix='.onnx', dir=directory)
        os.close(fd)
        try:
            urllib.request.urlretrieve(self.model_url, tmp_path)
            os.replace(tmp_path, self.model_path)
        except Exception as exc:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise RuntimeError(
                f'Failed to download ONNX model from {self.model_url}: {exc}'
            ) from exc
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f'Model not found after download: {self.model_path}')

    def letterbox(self, img: np.ndarray, new_shape: int):
        h, w = img.shape[:2]
        r = new_shape / max(h, w)
        nh, nw = int(round(h * r)), int(round(w * r))
        resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        top = (new_shape - nh) // 2
        bottom = new_shape - nh - top
        left = (new_shape - nw) // 2
        right = new_shape - nw - left
        padded = cv2.copyMakeBorder(
            resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114)
        )
        return padded, r, left, top

    def _postprocess_v5(
        self, pred: np.ndarray, orig_w: int, orig_h: int, r: float, pad_w: int, pad_h: int
    ):
        results = []
        for det in pred:
            objectness = float(det[4])
            cls_scores = det[5:]
            cls_id = int(np.argmax(cls_scores))
            conf = objectness * float(cls_scores[cls_id])
            if conf < self.conf_threshold:
                continue
            xc, yc, bw, bh = det[0], det[1], det[2], det[3]
            x1 = int((xc - bw / 2 - pad_w) / r)
            y1 = int((yc - bh / 2 - pad_h) / r)
            x2 = int((xc + bw / 2 - pad_w) / r)
            y2 = int((yc + bh / 2 - pad_h) / r)
            results.append((cls_id, conf, x1, y1, x2, y2))
        return results

    def _postprocess_v8(
        self, pred: np.ndarray, orig_w: int, orig_h: int, r: float, pad_w: int, pad_h: int
    ):
        # YOLOv8 ONNX output is [1, 4 + num_classes, num_anchors].
        if pred.ndim != 3:
            return []
        pred = pred[0]
        if pred.shape[0] < pred.shape[1]:
            pred = pred.T
        results = []
        for det in pred:
            cls_scores = det[4:]
            cls_id = int(np.argmax(cls_scores))
            conf = float(cls_scores[cls_id])
            if conf < self.conf_threshold:
                continue
            xc, yc, bw, bh = det[0], det[1], det[2], det[3]
            x1 = int((xc - bw / 2 - pad_w) / r)
            y1 = int((yc - bh / 2 - pad_h) / r)
            x2 = int((xc + bw / 2 - pad_w) / r)
            y2 = int((yc + bh / 2 - pad_h) / r)
            results.append((cls_id, conf, x1, y1, x2, y2))
        return results

    def detect(self, img: np.ndarray):
        orig_h, orig_w = img.shape[:2]
        resized, r, pad_w, pad_h = self.letterbox(img, self.input_size)
        blob = resized.transpose(2, 0, 1).astype(np.float32) / 255.0
        blob = np.expand_dims(blob, axis=0).astype(self.input_dtype)
        pred = self.session.run([self.output_name], {self.input_name: blob})[0]
        if pred.dtype == np.float16:
            pred = pred.astype(np.float32)

        if pred.ndim == 3 and pred.shape[2] == 85:
            results = self._postprocess_v5(pred[0], orig_w, orig_h, r, pad_w, pad_h)
        elif pred.ndim == 3 and pred.shape[1] == 85:
            # Some YOLOv5 exports keep the [1, 85, anchors] layout.
            pred = pred.transpose(0, 2, 1)
            results = self._postprocess_v5(pred[0], orig_w, orig_h, r, pad_w, pad_h)
        elif pred.ndim == 3 and pred.shape[1] >= 5:
            results = self._postprocess_v8(pred, orig_w, orig_h, r, pad_w, pad_h)
        else:
            results = []

        clipped = []
        for cls_id, conf, x1, y1, x2, y2 in results:
            x1 = max(0, min(orig_w - 1, x1))
            y1 = max(0, min(orig_h - 1, y1))
            x2 = max(0, min(orig_w - 1, x2))
            y2 = max(0, min(orig_h - 1, y2))
            if x2 <= x1 or y2 <= y1:
                continue
            clipped.append((cls_id, conf, x1, y1, x2, y2))

        boxes = [(b[2], b[3], b[4] - b[2], b[5] - b[3]) for b in clipped]
        confs = [b[1] for b in clipped]
        indices = cv2.dnn.NMSBoxes(boxes, confs, self.conf_threshold, self.nms_threshold)
        out = []
        if len(indices) > 0:
            for i in np.array(indices).flatten():
                cls_id, conf, x1, y1, x2, y2 = clipped[int(i)]
                out.append((cls_id, conf, x1, y1, x2, y2))
        return out
