"""Fetch or generate the demo clip.

The preferred clip is OpenCV's well-known `vtest.avi` (people walking), so the
real YOLO backend has something to detect. If the network is unavailable we
fall back to a synthetic clip, which is still useful with DETECTOR_BACKEND=mock.

Usage:
    python scripts/fetch_sample.py samples/sample.avi
"""

import argparse
import os
import sys
import urllib.request

VIDEO_URLS = [
    'https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/vtest.avi',
    'https://github.com/intel-iot-devkit/sample-videos/raw/master/people-detection.mp4',
]
IMAGE_URLS = [
    'https://ultralytics.com/images/bus.jpg',
    'https://raw.githubusercontent.com/ultralytics/ultralytics/main/ultralytics/assets/bus.jpg',
]


def _download(urls, destination, timeout=30):
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'video-analytics-demo/1.0'})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = response.read()
            if len(data) < 1024:
                continue
            with open(destination, 'wb') as fh:
                fh.write(data)
            print(f'[sample] downloaded {url} ({len(data)} bytes)')
            return True
        except Exception as exc:
            print(f'[sample] download failed for {url}: {exc}', file=sys.stderr)
    return False


def _synthetic(destination):
    try:
        import cv2
        import numpy as np
    except Exception as exc:
        print(f'[sample] cannot generate synthetic clip without OpenCV: {exc}', file=sys.stderr)
        return False
    width, height, fps, seconds = 640, 480, 20, 30
    writer = cv2.VideoWriter(destination, cv2.VideoWriter_fourcc(*'MJPG'), fps, (width, height))
    if not writer.isOpened():
        print(f'[sample] could not open video writer for {destination}', file=sys.stderr)
        return False
    total = fps * seconds
    for i in range(total):
        frame = np.full((height, width, 3), 30, np.uint8)
        x1 = int((i * 5) % (width - 120))
        y1 = int((i * 3) % (height - 180))
        cv2.rectangle(frame, (x1, y1), (x1 + 80, y1 + 160), (0, 200, 0), -1)
        x2 = int((width - 120) - (i * 4) % (width - 120))
        y2 = int((height - 160) - (i * 2) % (height - 160))
        cv2.rectangle(frame, (x2, y2), (x2 + 100, y2 + 120), (200, 120, 0), -1)
        writer.write(frame)
    writer.release()
    print(f'[sample] generated synthetic clip {destination} ({total} frames)')
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', nargs='?', default='samples/sample.avi')
    args = parser.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    if os.path.exists(args.output) and os.path.getsize(args.output) > 1024:
        print(f'[sample] {args.output} already exists')
    else:
        if not _download(VIDEO_URLS, args.output):
            if not _synthetic(args.output):
                return 1

    # Optional still frame for the detector sanity check and load test.
    frame_path = os.path.join(os.path.dirname(os.path.abspath(args.output)), 'bench_frame.jpg')
    if not os.path.exists(frame_path):
        _download(IMAGE_URLS, frame_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
