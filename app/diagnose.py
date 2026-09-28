"""M0 diagnostic: real CoreWLAN reading via the Swift helper. No fake values."""
import json, platform, subprocess, sys
from pathlib import Path

HELPER = Path(__file__).resolve().parent.parent / "bin" / "mac_wifi_reader"


def read_once() -> dict:
    out = subprocess.run([str(HELPER), "--once"], capture_output=True, text=True, timeout=5)
    if out.returncode != 0:
        raise RuntimeError(f"helper exit {out.returncode}: {out.stderr.strip()}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def status(s: dict) -> str:
    if not s["power_on"]:
        return "WIFI_POWER_OFF"
    if s["rssi_dbm"] == 0:
        return "NOT_ASSOCIATED (rssiValue()==0)"
    return "CONNECTED"


def main() -> int:
    if not HELPER.exists():
        print(f"Helper missing: {HELPER}\nBuild: swiftc -O helper/mac_wifi_reader.swift -o bin/mac_wifi_reader")
        return 2
    s = read_once()
    na = "unavailable (needs Location Services)"
    print("=" * 37, "MAC WI-FI DIAGNOSTIC", sep="\n")
    print(f"macOS:     {platform.mac_ver()[0]} ({platform.machine()})")
    print(f"Interface: {s['interface']}")
    print(f"SSID:      {s['ssid'] or na}")
    print(f"BSSID:     {s['bssid'] or na}")
    print(f"RSSI:      {s['rssi_dbm']} dBm")
    print(f"Noise:     {s['noise_dbm']} dBm")
    print(f"SNR:       {s['rssi_dbm'] - s['noise_dbm']} dB" if s["rssi_dbm"] else "SNR:       n/a")
    print(f"Channel:   {s['channel']} ({s['band']})")
    print(f"PHY:       {s['phy_mode']}")
    print(f"Tx rate:   {s['tx_rate_mbps']} Mbps")
    print(f"Read time: {s['read_ms']:.2f} ms")
    print(f"Status:    {status(s)}")
    print("=" * 37)
    return 0 if status(s) == "CONNECTED" else 1


if __name__ == "__main__":
    sys.exit(main())
