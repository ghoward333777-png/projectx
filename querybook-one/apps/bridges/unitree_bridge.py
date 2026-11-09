"""Unitree Go2 EDU / G1 EDU → QueryBook through unitree_sdk2_python (no ROS needed).

    pip install unitree_sdk2py   (see github.com/unitreerobotics/unitree_sdk2_python)
    QB_URL=http://<querybook-computer>:9101 QB_DEVICE_KEY=qbd_... python3 unitree_bridge.py go2 eth0

Sends: battery and mode as 'state' (every 30 s); Go2 foot contact forces as 'touch' when a foot lands.
For camera detections and G1 hand touch, use ros2_bridge.py with the robot's ROS 2 topics.
Untested against real robots in this release: message fields follow unitree_sdk2_python's examples — check them on your robot.
"""
import sys, time

from qb_device_client import from_env


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else "go2"
    iface = sys.argv[2] if len(sys.argv) > 2 else "eth0"
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
    if model == "go2":
        from unitree_sdk2py.idl.unitree_go.msg.dds_ import LowState_
    else:
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
    qb = from_env()
    ChannelFactoryInitialize(0, iface)
    state = {"last": 0, "contact": [False] * 4}

    def on_low(msg):
        now = time.time()
        if now - state["last"] >= 30:
            state["last"] = now
            bms = getattr(msg, "bms_state", None)
            qb.send("state", model=model, battery_pct=getattr(bms, "soc", None) if bms else None)
        forces = list(getattr(msg, "foot_force", []) or [])
        for i, f in enumerate(forces[:4]):
            down = f > 20
            if down and not state["contact"][i]:
                qb.send("touch", force_n=float(f), sensor="foot", location=["front-right", "front-left", "rear-right", "rear-left"][i])
            state["contact"][i] = down

    sub = ChannelSubscriber("rt/lowstate", LowState_)
    sub.Init(on_low, 10)
    print("Sending to QueryBook. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(2)
            qb.flush()
    except KeyboardInterrupt:
        qb.flush()


if __name__ == "__main__":
    main()
