#!/usr/bin/env python3
"""Device gateway: registration and keys, consent, every event kind, summaries, file imports, the network listener
(device API only) and the Python device client used by the bridges, against a running server."""
import base64, json, os, socket, sys, tempfile, threading, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "_core"))
sys.path.insert(0, os.path.join(ROOT, "bridges"))
import qbcore as core
import qbdevices as dv
from qb_device_client import Device

HEALTH = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_US">
 <Record type="HKQuantityTypeIdentifierHeartRate" unit="count/min" startDate="2026-10-18 08:00:00 -0400" endDate="2026-10-18 08:00:00 -0400" value="62"/>
 <Record type="HKQuantityTypeIdentifierHeartRate" unit="count/min" startDate="2026-10-18 09:00:00 -0400" endDate="2026-10-18 09:00:00 -0400" value="78"/>
 <Record type="HKQuantityTypeIdentifierStepCount" unit="count" startDate="2026-10-18 10:00:00 -0400" endDate="2026-10-18 10:10:00 -0400" value="1200"/>
 <Record type="HKQuantityTypeIdentifierStepCount" unit="count" startDate="2026-10-18 18:00:00 -0400" endDate="2026-10-18 18:10:00 -0400" value="800"/>
 <Record type="HKQuantityTypeIdentifierBodyMass" unit="kg" startDate="2026-10-18 07:00:00 -0400" endDate="2026-10-18 07:00:00 -0400" value="80"/>
</HealthData>"""
ARKIT_CSV = "Timecode,BlendshapeCount,EyeBlinkLeft,EyeBlinkRight,JawOpen,MouthClose\n" + "\n".join(
    "00:00:00:%02d.000,52,%s,%s,%.2f,0.1" % (i, "0.9" if i in (3, 4, 9) else "0.0", "0.9" if i in (3, 4, 9) else "0.0", 0.1 * (i % 5)) for i in range(12))
FIX_CSV = 'section id,recording id,fixation id,start timestamp [ns],end timestamp [ns],duration [ms],fixation x [px],fixation y [px]\n' + \
          "\n".join("s,r,%d,%d,%d,%d,800,600" % (i, 10 ** 18 + i * 10 ** 9, 10 ** 18 + i * 10 ** 9 + 250 * 10 ** 6, 250) for i in range(8))
GAZE_CSV = "section id,recording id,timestamp [ns],gaze x [px],gaze y [px],worn\n" + "\n".join(
    "s,r,%d,800,600,1" % (1760900000 * 10 ** 9 + i * 5 * 10 ** 6) for i in range(201))
BVH = """HIERARCHY
ROOT Hips
{
  OFFSET 0 0 0
  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation
  JOINT Spine
  {
    OFFSET 0 10 0
    CHANNELS 3 Zrotation Xrotation Yrotation
    End Site
    {
      OFFSET 0 10 0
    }
  }
}
MOTION
Frames: 3
Frame Time: 0.0333333
0 90 0 0 0 0 0 0 0
3 90 4 0 0 0 0 0 0
6 90 8 0 0 0 0 0 0
"""


def main():
    c = core.Checks()
    with tempfile.TemporaryDirectory() as tmp:
        hub = dv.Hub(tmp, "test")
        # registration and consent
        try:
            hub.register("Glasses", "ray-ban-meta-gen2", ["people"], "", False)
            refused = False
        except core.UserError:
            refused = True
        c.check("consent: a device recording people is refused without the person and their consent", refused)
        cam = hub.register("Desk camera", "insta360-link-2-pro")
        g = hub.register("Lab glasses", "ray-ban-meta-gen2", ["people", "location"], "Alex Test", True)
        h = hub.register("Chest strap", "polar-h10", ["body"], "Alex Test", True)
        c.check("register: each device gets its own key, stored only as a hash",
                g["token"].startswith("qbd_") and g["token"] != h["token"] and
                hub.store.scalar("SELECT count(*) FROM devices WHERE token_hash = ?", (dv._hash(g["token"]),)) == 1 and
                hub.store.scalar("SELECT count(*) FROM devices WHERE token_hash = ?", (g["token"],)) == 0)
        G, H, CAM = hub.authenticate(g["token"]), hub.authenticate(h["token"]), hub.authenticate(cam["token"])
        c.check("keys authenticate; a wrong key does not", G and G["name"] == "Lab glasses" and hub.authenticate("qbd_wrong") is None and hub.authenticate("") is None)
        # every kind
        r = hub.ingest(G, [{"kind": "detection", "data": {"label": "cup", "confidence": 0.9}, "t": 1760900000},
                           {"kind": "transcript", "data": {"text": "the meeting  starts at ten", "lang": "en"}},
                           {"kind": "gaze", "data": {"x": 0.5, "y": 0.4, "fixation_ms": 300, "target": "cup"}},
                           {"kind": "face", "data": {"blendshapes": {"jawOpen": 0.3, "eyeBlinkLeft": 0.1}}},
                           {"kind": "pose", "data": {"joints": {"hip": [0, 1, 0]}}},
                           {"kind": "location", "data": {"lat": 40.7128, "lon": -74.006, "accuracy_m": 8}},
                           {"kind": "touch", "data": {"force_n": 3.2, "location": "left hand"}},
                           {"kind": "state", "data": {"battery": 81}},
                           {"kind": "note", "data": {"text": "subject looked at the cup"}},
                           {"kind": "heart", "data": {"bpm": 70}},                       # refused: no body consent
                           {"kind": "wiggle", "data": {}},                               # refused: unknown kind
                           {"kind": "detection", "data": {"confidence": 2}}])            # refused: invalid
        c.check("ingest: valid events accepted, each refusal explained", r["accepted"] == 9 and len(r["refused"]) == 3 and
                "consent" in r["refused"][0]["error"] and "unknown kind" in r["refused"][1]["error"], r)
        r2 = hub.ingest(H, [{"kind": "heart", "t": "2026-10-19T10:00:05Z", "data": {"bpm": 60, "rr_ms": [1000]}},
                            {"kind": "heart", "t": "2026-10-19T10:00:35Z", "data": {"bpm": 80}},
                            {"kind": "ecg", "data": {"fs": 130, "uv": list(range(1300))}},
                            {"kind": "imu", "data": {"acc": [0, 0, 9.81]}}, {"kind": "steps", "data": {"count": 40}}])
        c.check("ingest: body signals with body consent", r2["accepted"] == 5, r2)
        m = hub.minutes(kind="heart_bpm")
        c.check("summary: heart rate kept as per-minute statistics", m and m[0]["n"] == 2 and m[0]["mean"] == 70 and m[0]["min"] == 60 and m[0]["max"] == 80, m)
        ecg = hub.store.one("SELECT data FROM events WHERE kind = 'ecg'")
        c.check("ECG: only a summary is stored, never the samples", '"seconds": 10.0' in ecg["data"] and "uv" not in json.loads(ecg["data"]), ecg)
        c.check("observations: the object seen can be asked about", hub.last_seen("CUP") and hub.last_seen("cup")["kind"] in ("detection", "gaze"))
        c.check("observations: transcripts, touches and places kept", {o["kind"] for o in hub.observations()} >= {"detection", "transcript", "touch", "location", "gaze", "ecg"})
        c.check("times: ISO and Unix (s/ms/ns) all accepted", dv._ts(1760900000) == dv._ts(1760900000000) == dv._ts(1760900000 * 10 ** 9) == "2025-10-19T18:53:20.00Z"
                and dv._ts("2026-10-18 08:00:00 -0400") == "2026-10-18T12:00:00.00Z")
        try:
            hub.ingest(G, [{"kind": "note", "data": {"text": "x"}}] * (dv.MAX_EVENTS + 1))
            big = False
        except core.UserError:
            big = True
        c.check("limits: at most %d events per request" % dv.MAX_EVENTS, big)
        # uploads
        try:
            hub.upload(H, "a.jpg", "photo", base64.b64encode(b"x").decode())
            nophoto = False
        except core.UserError:
            nophoto = True
        up = hub.upload(G, "../../etc/passwd snap.jpg", "photo", base64.b64encode(b"jpegbytes").decode())
        row = hub.store.one("SELECT * FROM inbox WHERE id = ?", (up["id"],))
        c.check("uploads: photos need people consent; files land in the inbox with a safe name and SHA-256", nophoto and
                os.path.dirname(row["path"]).startswith(os.path.join(tmp, "devices", "inbox")) and "/" not in row["name"] and len(up["sha256"]) == 64)
        # imports
        watch = hub.register("Watch", "apple-watch-ultra-3", ["body"], "Alex Test", True)
        W = hub.authenticate(watch["token"])
        ah = hub.import_file(W, "apple-health", HEALTH)
        daily = {o["label"]: o for o in hub.observations(kind="daily")}
        c.check("import: Apple Health export → daily summaries (unknown record types ignored)", ah["records"] == 4 and daily["heart_bpm"]["value"] == "70.0"
                and daily["steps"]["value"] == "2000.0" and "body" not in str(daily), (ah, daily))
        try:
            hub.import_file(CAM, "apple-health", HEALTH)
            gated = False
        except core.UserError:
            gated = True
        c.check("import: health data refused for a device without body consent", gated)
        ar = hub.import_file(G, "arkit-csv", ARKIT_CSV)
        c.check("import: ARKit face CSV (Live Link Face column names)", ar["frames"] == 12 and ar["channels"] == 4 and ar["blinks"] == 2, ar)
        fx = hub.import_file(G, "pupil-csv", FIX_CSV)
        gz = hub.import_file(G, "pupil-csv", GAZE_CSV)
        c.check("import: Pupil Labs fixations and gaze CSV", fx["fixations"] == 8 and fx["total_s"] == 2.0 and gz["samples"] == 201 and gz["seconds"] == 1.0, (fx, gz))
        bv = hub.import_file(G, "bvh", BVH)
        c.check("import: BVH motion capture", bv["joints"] == 2 and bv["frames"] == 3 and abs(bv["root_travel"] - 10.0) < 0.01, bv)
        jl = hub.import_file(G, "jsonl", '{"kind":"detection","data":{"label":"book"}}\n{"kind":"heart","data":{"bpm":70}}\n')
        c.check("import: JSON-lines events go through the same checks", jl["accepted"] == 1 and len(jl["refused"]) == 1)
        # revoke, prune, spec
        hub.revoke(h["id"])
        c.check("revoke: the key stops working", hub.authenticate(h["token"]) is None)
        hub.save_settings(retain_days=1)
        with hub.store.write() as d:
            d.execute("UPDATE events SET t = '2000-01-01T00:00:00Z' WHERE kind = 'state'")
        pr = hub.prune()
        c.check("retention: old raw events pruned, summaries kept", pr["pruned"] >= 1 and hub.store.scalar("SELECT count(*) FROM events WHERE kind = 'state'") == 0
                and hub.minutes(kind="heart_bpm") and hub.last_seen("cup"), pr)
        spec = dv.openapi()
        c.check("OpenAPI description", spec["openapi"].startswith("3.") and "/api/devices/ingest" in spec["paths"] and set(spec["components"]["schemas"]["Event"]["properties"]["kind"]["enum"]) == set(dv.KINDS))
        c.check("catalog covers every recommended device", {"insta360-link-2-pro", "logitech-mx-brio", "iphone-17-pro", "pixel-10-pro", "ray-ban-meta-gen2", "meta-ray-ban-display",
                "unitree-g1-edu", "hello-robot-stretch-3", "gelsight-mini", "unitree-go2-edu", "turtlebot-4", "polar-h10", "polar-verity-sense", "apple-watch-ultra-3",
                "rokoko-smartsuit-pro-2", "pupil-labs-neon", "tobii-pro-glasses-3", "dji-mic-2", "rode-wireless-pro"} <= set(dv.CATALOG_BY_ID))

        # the application server (this computer) and the network listener (device API only), with the bridge client
        api = core.Api()
        dv.add_routes(api, hub)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), core.make_handler(api, tmp, lambda *a: None, "Test"))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        local = "http://127.0.0.1:%d" % srv.server_address[1]
        out = Device(local, g["token"], spool=os.path.join(tmp, "spool1.jsonl"))
        out.send("detection", label="lamp", confidence=0.8)
        res = out.flush()
        c.check("client → application server with a Bearer key", res.get("accepted") == 1 and hub.last_seen("lamp"), res)
        try:
            bad = Device(local, "qbd_bad", spool=os.path.join(tmp, "spool2.jsonl"))
            bad.send("note", text="x")
            bad.flush()
            badkey = False
        except urllib.error.HTTPError as e:
            badkey = e.code == 400
        c.check("client: a bad key is refused, not retried forever", badkey)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
        st = hub.start_lan(port)
        lan = "http://127.0.0.1:%d" % port
        c.check("network listener starts", st["running"] and st["port"] == port)
        dead = Device("http://127.0.0.1:9", g["token"], spool=os.path.join(tmp, "spool3.jsonl"))
        dead.send("detection", label="kettle")
        sp = dead.flush()
        dead.url = lan
        dead.send("detection", label="mug")
        res = dead.flush()
        c.check("client: events kept while QueryBook is unreachable, delivered later", sp.get("spooled") == 1 and res.get("accepted") == 2 and hub.last_seen("kettle"), (sp, res))
        c.check("network listener: ping with the key", dead.ping()["ok"])

        def code(url, data=None):
            try:
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                return urllib.request.urlopen(req, timeout=5).status
            except urllib.error.HTTPError as e:
                return e.code
        c.check("network listener: only the device API — no application pages or other actions",
                code(lan + "/") == 404 and code(lan + "/api/devices/status") == 404 and code(lan + "/api/devices/register", b"{}") == 404 and
                code(lan + "/api/devices/openapi.json") == 200 and code(lan + "/api/devices/ingest", b'{"events":[{"kind":"note","data":{"text":"x"}}]}') == 401)
        hub.stop_lan()
        srv.shutdown()
        hub.store.conn().close()
    return c.report("Device gateway (API, consent, imports, network listener, bridge client)")


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
