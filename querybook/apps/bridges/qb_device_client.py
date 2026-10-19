"""Tiny client for the QueryBook device API (standard Python only). Every Python bridge here uses it.

    from qb_device_client import Device
    qb = Device("http://192.168.1.20:9101", "qbd_...")      # the address shown on QueryBook's Devices page
    qb.send("detection", label="cup", confidence=0.9)        # buffered; sent in batches
    qb.flush()

Events wait in memory (and, if QueryBook cannot be reached, in a local file) and are sent in batches, so a robot or
wearable keeps working through network gaps. Nothing but the events you send leaves the device.
"""
import json, os, threading, time, urllib.error, urllib.request

KINDS = {"heart", "ecg", "imu", "steps", "gaze", "face", "pose", "transcript", "location", "detection", "touch", "state", "note"}


class Device:
    def __init__(self, url, key, batch=200, every_s=2.0, spool=None):
        self.url = url.rstrip("/")
        self.key = key
        self.batch, self.every_s = batch, every_s
        self.spool = spool or os.path.join(os.path.expanduser("~"), ".querybook-device-spool.jsonl")
        self._buf, self._lock, self._last = [], threading.Lock(), time.time()

    def _post(self, path, body):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))

    def ping(self):
        req = urllib.request.Request(self.url + "/api/devices/ping", headers={"Authorization": "Bearer " + self.key})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def send(self, kind, t=None, subject=None, **data):
        if kind not in KINDS:
            raise ValueError("unknown kind %s" % kind)
        ev = {"kind": kind, "t": t if t is not None else time.time(), "data": data}
        if subject:
            ev["subject"] = subject
        with self._lock:
            self._buf.append(ev)
            due = len(self._buf) >= self.batch or time.time() - self._last >= self.every_s
        if due:
            self.flush()

    def flush(self):
        with self._lock:
            events, self._buf, self._last = self._buf, [], time.time()
        events = self._unspool() + events
        if not events:
            return {"accepted": 0}
        try:
            out = {"accepted": 0, "refused": []}
            for i in range(0, len(events), 2000):
                r = self._post("/api/devices/ingest", {"events": events[i:i + 2000]})
                out["accepted"] += r.get("accepted", 0)
                out["refused"] += r.get("refused", [])
            return out
        except (urllib.error.URLError, OSError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code in (400, 401, 413):
                raise                                   # a bad key or bad events: do not keep retrying
            with open(self.spool, "a", encoding="utf-8") as f:
                for ev in events:
                    f.write(json.dumps(ev) + "\n")
            return {"accepted": 0, "spooled": len(events), "error": str(e)}

    def _unspool(self):
        if not os.path.exists(self.spool):
            return []
        with open(self.spool, encoding="utf-8") as f:
            events = [json.loads(l) for l in f if l.strip()]
        os.remove(self.spool)
        return events

    def upload(self, path, kind="file", note=None):
        import base64
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        return self._post("/api/devices/upload", {"name": os.path.basename(path), "kind": kind, "data_b64": data, "note": note})


def from_env():
    """QB_URL and QB_DEVICE_KEY from the environment (how the bridges are configured)."""
    url, key = os.environ.get("QB_URL"), os.environ.get("QB_DEVICE_KEY")
    if not url or not key:
        raise SystemExit("Set QB_URL (e.g. http://192.168.1.20:9101) and QB_DEVICE_KEY (qbd_...) first.")
    return Device(url, key)
