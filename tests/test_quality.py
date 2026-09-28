import numpy as np
from app.quality import analyze, warnings


def mk(rssi, dt=0.2, seq=None, ch=None):
    n = len(rssi)
    return {"t": np.arange(n) * dt, "seq": np.array(seq if seq is not None else range(n)),
            "rssi": np.array(rssi, float), "noise": np.full(n, -90.0),
            "channel": np.array(ch or ["36"] * n)}


def test_rate_and_stats():
    q = analyze(mk([-60, -62, -61, -63, -60]), requested_hz=5)
    assert abs(q.actual_hz - 5) < 1e-9
    assert q.median == -61 and q.mad == 1 and not q.constant


def test_flags_constant_zero_dup_and_channel():
    d = mk([-50, -50, 0, -50], seq=[0, 1, 1, 2], ch=["36", "36", "40", "40"])
    q = analyze(d)
    assert q.constant and q.zero_rssi == 1 and q.duplicate_seq == 1 and q.channel_changes == 1
    assert len(warnings(q)) >= 3


def test_missing_from_gap():
    d = mk([-60] * 5)
    d["t"] = np.array([0, 0.2, 0.4, 1.0, 1.2])
    assert analyze(d).missing == 2
