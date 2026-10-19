# QueryBook device bridges

Small programs that run beside a device and send its **observations** to QueryBook's device API
(`/api/devices/ingest`, described in `GET /api/devices/openapi.json`). They contain no QueryBook application code.

1. In QueryBook open **Devices**, register the device (with the person's consent if it records people, body signals or
   location) and copy its key.
2. If the device is not this computer, tick **Accept devices on my home network**; the page shows the address to use
   (port 9101 / 9102 / 9103 for Language / Math & Science / History & News).
3. Run the bridge with `QB_URL` and `QB_DEVICE_KEY` set.

| Device | Bridge | Needs |
|---|---|---|
| Any device or program | `qb_device_client.py` (used by all Python bridges) | Python 3.8+ only |
| Hello Robot Stretch 3, TurtleBot 4, Unitree G1/Go2 (ROS 2), any ROS 2 robot | `ros2_bridge.py` | ROS 2 Humble+ (rclpy) |
| Unitree Go2 EDU / G1 EDU (no ROS) | `unitree_bridge.py` | unitree_sdk2py |
| Polar H10 / Verity Sense (heart rate, H10 ECG) | `polar_bridge.py` (heart rate also works in the browser) | bleak |
| Pupil Labs Neon | `pupil_neon_bridge.py` | pupil-labs-realtime-api |
| Tobii Pro Glasses 3 | `tobii_bridge.py` (template) | g3pylib |
| GelSight Mini | `gelsight_bridge.py` | opencv-python, numpy |
| Rokoko Smartsuit Pro II (live) | `rokoko_bridge.py` | — (UDP from Rokoko Studio Live) |
| iPhone with Face ID | `iphone_arkit/FaceSender.swift` | Xcode, an iPhone app of your own |
| Ray-Ban Meta Gen 2 / Meta Ray-Ban Display | `meta_glasses/QueryBookSender.kt` (template) | Android app with Meta's Wearables Device Access Toolkit |

Built into the QueryBook page (no bridge): webcams (Insta360 Link 2 Pro, Logitech MX Brio) with pan/tilt/zoom controls,
Bluetooth heart-rate straps, and file imports — Apple Health export (Apple Watch), ARKit face CSV (Live Link Face),
Pupil Labs gaze/fixation CSV, BVH motion capture, JSON-lines events. Microphone recordings (DJI Mic 2, Rode Wireless PRO)
go to Language Builder's speech-to-text.

**Status:** the client library is tested against QueryBook. The bridges follow each maker's published SDK but have not
been run on the real hardware in this release — test each with your device; only the `qb.send(...)` calls touch QueryBook.

**Event kinds:** heart, ecg (summary kept), imu, steps, gaze, face, pose, transcript, location, detection, touch, state,
note. Events of a kind the device's consent does not cover are refused. Send observations, not recordings.
