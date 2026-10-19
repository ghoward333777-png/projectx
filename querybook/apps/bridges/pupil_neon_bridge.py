"""Pupil Labs Neon → QueryBook through the Neon Realtime API.

    pip install pupil-labs-realtime-api
    QB_URL=http://127.0.0.1:8101 QB_DEVICE_KEY=qbd_... python3 pupil_neon_bridge.py [target-label]

The Neon Companion phone and this computer must be on the same network. Gaze is averaged to 5 points a second
(normalised 0–1 in the scene camera image). Give a target label (e.g. "cup") while a directed subject looks at an object
under study; the label is attached to the gaze events. The device needs 'people' consent. Untested on hardware here.
"""
import sys, time

from pupil_labs.realtime_api.simple import discover_one_device

from qb_device_client import from_env


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None
    qb = from_env()
    device = discover_one_device(max_search_duration_seconds=15)
    if device is None:
        raise SystemExit("No Neon found on the network.")
    print("Connected to", device, "— sending gaze to QueryBook. Ctrl+C to stop.")
    xs, ys, t0 = [], [], time.time()
    try:
        while True:
            g = device.receive_gaze_datum()
            if getattr(g, "worn", True):
                xs.append(g.x / 1600.0)                   # Neon scene camera: 1600 × 1200 px
                ys.append(g.y / 1200.0)
            if time.time() - t0 >= 0.2 and xs:
                qb.send("gaze", x=round(sum(xs) / len(xs), 4), y=round(sum(ys) / len(ys), 4), **({"target": target} if target else {}))
                xs, ys, t0 = [], [], time.time()
    except KeyboardInterrupt:
        pass
    finally:
        qb.flush()
        device.close()


if __name__ == "__main__":
    main()
