from app.activity import ActivityMeter


def test_quiet_then_changing_signal_raises_level():
    m = ActivityMeter(hz=5, history_s=20)
    for i in range(100):                      # quiet: 1 dB quantization flicker
        r = m.update(-60 - (i % 7 == 0))
    assert r["level"] == "LOW"
    for i in range(15):                       # large swings
        r = m.update(-60 + (6 if i % 2 else -6))
    assert r["level"] == "HIGH" and r["intensity"] > 0.5


def test_warmup_reported_before_history_fills():
    assert ActivityMeter(hz=5).update(-60)["level"] == "WARMUP"
