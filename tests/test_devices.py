import json
from pathlib import Path

import pytest

from app import devices


def test_free_space_loss_5ghz_1m():
    assert abs(devices.free_space_loss_db(1, 5180) - 46.7) < 0.2


def test_wall_estimate_range_contains_point():
    w = devices.wall_estimate(-72, 36, 4)
    lo, hi = w["excess_range_db"]
    assert lo < w["excess_db"] < hi and w["drywall_equiv"][0] <= w["drywall_equiv"][1]


def test_lan_parse_skips_broadcast_and_flags_random_mac(monkeypatch):
    out = ("? (192.168.1.1) at 50:f:f5:1:2:3 on en0 ifscope [ethernet]\n"
           "? (192.168.1.40) at 6a:1:2:3:4:5 on en0 ifscope [ethernet]\n"
           "? (192.168.1.255) at ff:ff:ff:ff:ff:ff on en0 ifscope [ethernet]\n")
    monkeypatch.setattr(devices.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": out})())
    d = devices.lan_devices()
    assert [x["ip"] for x in d] == ["192.168.1.1", "192.168.1.40"]
    assert d[0]["mac_prefix"] == "50:0f:f5" and not d[0]["random_mac"] and d[1]["random_mac"]


@pytest.mark.parametrize("channel, band, mhz", [
    (6, "2.4GHz", 2437), (14, "2.4GHz", 2484),     # ch 14 is off the 5 MHz grid (Japan)
    (36, "5GHz", 5180), (149, "5GHz", 5745),
    (5, "6GHz", 5975), (37, "6GHz", 6135), (2, "6GHz", 5935),
    (11, None, 2462), (44, None, 5220),            # band unknown: guess from channel number
])
def test_channel_to_frequency_uses_band(channel, band, mhz):
    assert devices.channel_mhz(channel, band) == mhz


def test_wall_estimate_uses_6ghz_frequency():
    w = devices.wall_estimate(-72, 37, 4, band="6GHz")
    assert w["freq_mhz"] == 6135
    assert w["expected_dbm"] == pytest.approx(20 - devices.free_space_loss_db(4, 6135))


def test_band_reaches_wall_estimate_from_live_sample(monkeypatch):
    from app import visual
    from app.backend import RssiSample

    s = RssiSample(timestamp="t", t_mono=0.0, seq=0, interface="en0", rssi_dbm=-72, noise_dbm=-94,
                   channel=37, band="6GHz", phy_mode="802.11ax", tx_rate_mbps=1200, ssid=None, read_ms=1)
    monkeypatch.setattr(visual, "load_calibration", lambda: None)
    monkeypatch.setattr(visual, "load_rules", lambda: None)
    monkeypatch.setattr(visual, "replay_stream", lambda path: iter([s]))
    hub = visual.Hub()
    visual.collector(hub, hz=5, replay=Path("x.csv"))

    class NoBle:
        def start(self): return False
        def read(self): return None

    class Stop(Exception):
        pass

    def stop(_):
        raise Stop

    monkeypatch.setattr(devices, "BleReader", NoBle)
    monkeypatch.setattr(visual.time, "sleep", stop)   # end devices_loop after its first publish
    with pytest.raises(Stop):
        visual.devices_loop(hub, lan=False, router_distance=4)
    assert json.loads(hub.events[-1])["wall"]["freq_mhz"] == 6135
