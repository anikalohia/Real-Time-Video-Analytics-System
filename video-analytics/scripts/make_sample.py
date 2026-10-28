"""Generate a synthetic sample video (moving rectangles) for local demos.

Usage:
    python scripts/make_sample.py samples/sample.mp4 --seconds 20
"""

import argparse
import os

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out', nargs='?', default='samples/sample.mp4')
    ap.add_argument('--seconds', type=int, default=20)
    ap.add_argument('--fps', type=int, default=20)
    ap.add_argument('--width', type=int, default=1280)
    ap.add_argument('--height', type=int, default=720)
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(args.out, fourcc, args.fps, (args.width, args.height))

    total = args.seconds * args.fps
    for i in range(total):
        frame = np.full((args.height, args.width, 3), 30, np.uint8)
        cv2.putText(
            frame, f'frame {i}', (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2
        )
        # moving "person" boxes
        x1 = int((i * 7) % (args.width - 120))
        y1 = int((i * 3) % (args.height - 200))
        cv2.rectangle(frame, (x1, y1), (x1 + 80, y1 + 180), (0, 200, 0), -1)
        x2 = int((args.width - 120) - (i * 5) % (args.width - 120))
        y2 = int((args.height - 180) - (i * 4) % (args.height - 180))
        cv2.rectangle(frame, (x2, y2), (x2 + 100, y2 + 120), (200, 120, 0), -1)
        writer.write(frame)

    writer.release()
    print(f'wrote {args.out} ({total} frames)')


if __name__ == '__main__':
    main()
