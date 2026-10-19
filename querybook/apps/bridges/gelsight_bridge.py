"""GelSight Mini (USB camera-based touch sensor) → QueryBook 'touch' events.

    pip install opencv-python numpy
    QB_URL=http://127.0.0.1:8101 QB_DEVICE_KEY=qbd_... python3 gelsight_bridge.py [camera-index] [location]

The first frames (nothing touching) are the reference. A touch is the area of the gel that changes; contact area is
converted with the gel's size (about 18.6 × 14.3 mm), and a rough force estimate comes from the depth of change
(calibrate FORCE_PER_UNIT with a known weight for real numbers). One event per touch.
"""
import sys, time

import cv2
import numpy as np

from qb_device_client import from_env

GEL_MM = (18.6, 14.3)
FORCE_PER_UNIT = 0.002          # newtons per unit of summed change — calibrate with a known weight


def main():
    cam = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    where = sys.argv[2] if len(sys.argv) > 2 else "gripper"
    qb = from_env()
    cap = cv2.VideoCapture(cam)
    frames = [cv2.cvtColor(cap.read()[1], cv2.COLOR_BGR2GRAY).astype(np.float32) for _ in range(20)]
    ref = np.mean(frames, axis=0)
    touching, peak = False, (0, 0)
    print("Reference taken — touch the gel. Ctrl+C to stop.")
    try:
        while True:
            ok, f = cap.read()
            if not ok:
                break
            diff = np.abs(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) - ref)
            mask = diff > 18
            frac = float(mask.mean())
            if frac > 0.01:
                touching = True
                peak = max(peak, (frac, float(diff[mask].sum())))
            elif touching:
                area = peak[0] * GEL_MM[0] * GEL_MM[1]
                qb.send("touch", contact_area_mm2=round(area, 2), force_n=round(peak[1] * FORCE_PER_UNIT / 1000, 3), sensor="gelsight-mini", location=where)
                qb.flush()
                touching, peak = False, (0, 0)
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        qb.flush()
        cap.release()


if __name__ == "__main__":
    main()
