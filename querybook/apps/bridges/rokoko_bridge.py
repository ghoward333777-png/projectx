"""Rokoko Smartsuit Pro II (via Rokoko Studio Live) → QueryBook 'pose' events.

In Rokoko Studio: Livestreaming → Custom → JSON (v3), target this computer, port 14043. Then:
    QB_URL=http://127.0.0.1:8101 QB_DEVICE_KEY=qbd_... python3 rokoko_bridge.py [port]

Sends a reduced pose (hips, head, hands, feet) twice a second — enough to record gestures and posture without
storing the full motion stream. Use BVH export + the Devices page import for whole recordings. Needs 'people' consent.
"""
import json, socket, sys, time

from qb_device_client import from_env

JOINTS = ("hip", "head", "leftHand", "rightHand", "leftFoot", "rightFoot")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 14043
    qb = from_env()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", port))
    print("Listening for Rokoko Studio Live on UDP", port)
    last = 0
    while True:
        data, _ = s.recvfrom(1 << 20)
        if time.time() - last < 0.5:
            continue
        try:
            msg = json.loads(data.decode("utf-8"))
        except ValueError:
            continue
        for actor in (msg.get("scene") or {}).get("actors", []):
            body = actor.get("body") or {}
            joints = {j: [body[j]["position"][a] for a in ("x", "y", "z")] for j in JOINTS if j in body and "position" in body[j]}
            if joints:
                qb.send("pose", subject=actor.get("name"), joints=joints)
        last = time.time()
        qb.flush()


if __name__ == "__main__":
    main()
