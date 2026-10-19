"""Tobii Pro Glasses 3 → QueryBook (gaze), using Tobii's g3pylib Python library.

    pip install g3pylib   (github.com/tobiipro/g3pylib)
    QB_URL=http://127.0.0.1:8101 QB_DEVICE_KEY=qbd_... python3 tobii_bridge.py <glasses-hostname>

Gaze 2D (normalised 0–1) is averaged to 5 points a second. The device needs 'people' consent.
Template: follow g3pylib's streaming example if its API differs in your version — only the qb.send(...) line matters here.
"""
import asyncio, sys, time

from qb_device_client import from_env


async def main(host):
    from g3pylib import connect_to_glasses
    qb = from_env()
    async with connect_to_glasses.with_hostname(host) as g3:
        async with g3.stream_rtsp(scene_camera=False, gaze=True) as streams:
            async with streams.gaze.decode() as gaze_stream:
                xs, ys, t0 = [], [], time.time()
                while True:
                    gaze, _ts = await gaze_stream.get()
                    p = (gaze or {}).get("gaze2d")
                    if p:
                        xs.append(p[0]); ys.append(p[1])
                    if time.time() - t0 >= 0.2 and xs:
                        qb.send("gaze", x=round(sum(xs) / len(xs), 4), y=round(sum(ys) / len(ys), 4))
                        xs, ys, t0 = [], [], time.time()
                        qb.flush()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "tg03b-080200000000"))
