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
