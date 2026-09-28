from app.classifier import LiveClassifier, classify

RULES = {"window_s": 3, "baseline_mean_dbm": -70.0, "presence_std_db": 1.44,
         "presence_shift_db": 1.68, "active_dE": 0.64}


def f(std, shift, dE):
    return {"std": std, "shift": shift, "dE": dE}


def test_rules():
    assert classify(f(0.3, 0.2, 0.1), RULES)[0] == "ABSENT"
    assert classify(f(0.8, 6.0, 0.2), RULES)[0] == "PRESENT_STILL"
    assert classify(f(1.8, 4.0, 2.0), RULES)[0] == "ACTIVE"


def test_live_needs_full_window_then_reports():
    lc = LiveClassifier(5, RULES)
    assert lc.update(-70) is None
    for _ in range(20):
        out = lc.update(-70)
    assert out["state"] == "ABSENT" and 0 < out["confidence"] <= 1
