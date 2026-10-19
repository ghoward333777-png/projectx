"""ROS 2 → QueryBook: for Hello Robot Stretch 3, TurtleBot 4, Unitree G1/Go2 (ROS 2) and any ROS 2 robot.

Needs ROS 2 (Humble or newer) with rclpy; run inside the robot's ROS 2 environment:
    QB_URL=http://<querybook-computer>:9101 QB_DEVICE_KEY=qbd_... python3 ros2_bridge.py
Topics (override with ROS parameters, e.g. --ros-args -p detections:=/my/detections):
    detections  vision_msgs/Detection2DArray    → 'detection' events (label = class id or hypothesis)
    transcript  std_msgs/String                 → 'transcript' events (speech recogniser output)
    battery     sensor_msgs/BatteryState        → 'state' events (every 30 s)
    wrench      geometry_msgs/WrenchStamped     → 'touch' events (force above the threshold, e.g. gripper or wrist sensor)
    hazards     irobot_create_msgs/HazardDetectionVector (TurtleBot 4 bumpers) → 'touch' events
Untested against real robots in this release: check topic names with `ros2 topic list` on your robot.
"""
import math, time

import rclpy
from rclpy.node import Node

from qb_device_client import from_env


class Bridge(Node):
    def __init__(self):
        super().__init__("querybook_bridge")
        self.qb = from_env()
        p = {"detections": "/detections", "transcript": "/speech/text", "battery": "/battery_state", "wrench": "/wrist_wrench",
             "hazards": "/hazard_detection", "force_threshold_n": 2.0, "min_confidence": 0.5}
        for k, v in p.items():
            self.declare_parameter(k, v)
        g = lambda k: self.get_parameter(k).value
        self.thr, self.minconf, self._last_batt, self._seen = g("force_threshold_n"), g("min_confidence"), 0, {}
        self._sub("vision_msgs.msg", "Detection2DArray", g("detections"), self.on_det)
        self._sub("std_msgs.msg", "String", g("transcript"), lambda m: self.qb.send("transcript", text=m.data))
        self._sub("sensor_msgs.msg", "BatteryState", g("battery"), self.on_batt)
        self._sub("geometry_msgs.msg", "WrenchStamped", g("wrench"), self.on_wrench)
        self._sub("irobot_create_msgs.msg", "HazardDetectionVector", g("hazards"), self.on_hazard)
        self.create_timer(2.0, self.qb.flush)

    def _sub(self, module, name, topic, cb):
        try:
            mod = __import__(module, fromlist=[name])
            self.create_subscription(getattr(mod, name), topic, cb, 10)
            self.get_logger().info("listening to %s (%s)" % (topic, name))
        except (ImportError, AttributeError):
            self.get_logger().info("%s.%s not installed: %s skipped" % (module, name, topic))

    def on_det(self, msg):
        now = time.time()
        for d in msg.detections:
            if not d.results:
                continue
            h = max(d.results, key=lambda r: r.hypothesis.score)
            label, conf = str(h.hypothesis.class_id), float(h.hypothesis.score)
            if conf < self.minconf or now - self._seen.get(label, 0) < 5:      # one event per label every 5 s
                continue
            self._seen[label] = now
            self.qb.send("detection", label=label, confidence=round(conf, 3))

    def on_batt(self, m):
        if time.time() - self._last_batt >= 30:
            self._last_batt = time.time()
            self.qb.send("state", battery_pct=round(float(m.percentage) * 100, 1), voltage=round(float(m.voltage), 2))

    def on_wrench(self, m):
        f = m.wrench.force
        n = math.sqrt(f.x ** 2 + f.y ** 2 + f.z ** 2)
        if n >= self.thr:
            self.qb.send("touch", force_n=round(n, 2), sensor="wrench", location=m.header.frame_id or "wrist")

    def on_hazard(self, m):
        for h in m.detections:
            if h.type == 1:                                   # BUMP
                self.qb.send("touch", contact_area_mm2=0, sensor="bumper", location=h.header.frame_id or "bumper")


def main():
    rclpy.init()
    node = Bridge()
    try:
        rclpy.spin(node)
    finally:
        node.qb.flush()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
