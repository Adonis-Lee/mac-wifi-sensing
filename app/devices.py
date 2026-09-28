"""Other RF / network devices and a coarse wall-loss estimate. All values are measured or
explicitly marked as estimates.

- BLE: nearby Bluetooth LE advertisers with RSSI (MacBLE.app, CoreBluetooth).
- LAN: devices the Mac already knows on its own network (passive ARP cache read; opt-in).
- Wall estimate: measured link RSSI vs free-space prediction for a user-given router distance.
  This is NOT wall detection; it is an excess-path-loss figure with wide uncertainty.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLE_APP = ROOT / "bin" / "MacBLE.app"
BLE_OUT = ROOT / "data" / "tmp" / "ble.json"


class BleReader:
    def __init__(self):
        BLE_OUT.parent.mkdir(parents=True, exist_ok=True)
        self.alive = BLE_OUT.with_name(BLE_OUT.name + ".alive")
        self.started = False

    def start(self) -> bool:
        if not BLE_APP.exists():
            return False
        self.alive.touch()
        # one instance only: two scanners race on the same snapshot file
        subprocess.run(["pkill", "-f", "MacBLE.app/Contents/MacOS/mac_ble_reader"], check=False)
        time.sleep(0.5)
        subprocess.run(["open", "-g", "-n", str(BLE_APP), "--args", "--out", str(BLE_OUT)], check=False)
        self.started = True
        return True

    def read(self) -> dict | None:
        self.alive.touch()  # heartbeat: the app exits ~20 s after we stop touching this
        try:
            return json.loads(BLE_OUT.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return None


ARP_RE = re.compile(r"\((\d+\.\d+\.\d+\.\d+)\) at ([0-9a-f:]+) on (\w+)")


def lan_devices(interface: str = "en0") -> list[dict]:
    """Passive: parse the kernel ARP cache (no probing). MACs are truncated for privacy."""
    out = subprocess.run(["arp", "-an", "-i", interface], capture_output=True, text=True).stdout
    devs = []
    for ip, mac, _ in ARP_RE.findall(out):
        if mac == "ff:ff:ff:ff:ff:ff" or ip.startswith("224.") or ip.endswith(".255"):
            continue
        first = int(mac.split(":")[0], 16)
        octets = [o.zfill(2) for o in mac.split(":")]
        devs.append({"ip": ip, "mac_prefix": ":".join(octets[:3]),
                     "random_mac": bool(first & 0x02)})  # locally administered = private/random MAC
    return devs


def free_space_loss_db(distance_m: float, freq_mhz: float) -> float:
    return 20 * math.log10(max(distance_m, 0.1)) + 20 * math.log10(freq_mhz) - 27.55


CH_MHZ = lambda ch: 2407 + 5 * ch if ch <= 14 else 5000 + 5 * ch


def wall_estimate(rssi_dbm: float, channel: int, distance_m: float,
                  eirp_dbm: float = 20.0, eirp_unc_db: float = 6.0) -> dict:
    """Excess loss over free space. eirp is an assumption (typical home router), hence the range.
    Per-wall loss at 5 GHz ~3-6 dB drywall, ~10-15 dB brick/concrete (literature ranges)."""
    expected = eirp_dbm - free_space_loss_db(distance_m, CH_MHZ(channel))
    excess = expected - rssi_dbm
    lo, hi = excess - eirp_unc_db, excess + eirp_unc_db
    return {"expected_dbm": expected, "excess_db": excess, "excess_range_db": [lo, hi],
            "drywall_equiv": [max(0, math.floor(lo / 6)), max(0, math.ceil(hi / 3))],
            "assumed_eirp_dbm": eirp_dbm, "distance_m": distance_m}
