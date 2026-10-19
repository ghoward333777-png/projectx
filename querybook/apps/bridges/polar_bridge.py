"""Polar H10 / Verity Sense → QueryBook over Bluetooth (heart rate, RR intervals, and H10 raw ECG summaries).

    pip install bleak
    QB_URL=http://127.0.0.1:8101 QB_DEVICE_KEY=qbd_... python3 polar_bridge.py [--ecg]

Heart rate uses the standard Bluetooth Heart Rate service (works with any chest strap). --ecg starts the H10's ECG stream
through Polar's measurement service (PMD, documented in Polar's open BLE SDK); QueryBook keeps only a summary per
segment. The device needs 'body' consent in QueryBook. Untested on hardware in this release.
"""
import asyncio, struct, sys, time

from bleak import BleakClient, BleakScanner

from qb_device_client import from_env

HR = "00002a37-0000-1000-8000-00805f9b34fb"
PMD_CP = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"
PMD_DATA = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"
ECG_START = bytearray([0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00])   # ECG, 130 Hz, 14-bit


async def main(ecg):
    qb = from_env()
    dev = await BleakScanner.find_device_by_filter(lambda d, ad: (d.name or "").startswith("Polar"), timeout=20)
    if not dev:
        raise SystemExit("No Polar device found. Wear it (the strap needs skin contact) and try again.")
    samples = []

    def on_hr(_, data):
        flags = data[0]
        bpm = struct.unpack_from("<H", data, 1)[0] if flags & 1 else data[1]
        i = 3 if flags & 1 else 2
        i += 2 if flags & 0x08 else 0
        rr = [round(struct.unpack_from("<H", data, j)[0] * 1000 / 1024) for j in range(i, len(data) - 1, 2)] if flags & 0x10 else []
        qb.send("heart", bpm=bpm, **({"rr_ms": rr} if rr else {}))

    def on_pmd(_, data):
        if data[0] != 0x00:                               # 0x00 = ECG frame
            return
        for j in range(10, len(data) - 2, 3):
            v = int.from_bytes(data[j:j + 3], "little", signed=True)
            samples.append(v)
        if len(samples) >= 130 * 10:                      # a 10-second segment
            qb.send("ecg", fs=130, uv=samples[:])
            samples.clear()

    async with BleakClient(dev) as c:
        await c.start_notify(HR, on_hr)
        if ecg:
            await c.start_notify(PMD_DATA, on_pmd)
            await c.write_gatt_char(PMD_CP, ECG_START, response=True)
        print("Connected to", dev.name, "— sending to QueryBook. Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(2)
                qb.flush()
        finally:
            qb.flush()


if __name__ == "__main__":
    asyncio.run(main("--ecg" in sys.argv))
