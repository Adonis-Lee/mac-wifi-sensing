import csv
import json

import numpy as np

from app import calibrate, classifier
from app.activity import ActivityMeter
from app.classifier import LiveClassifier, classify

HZ = 5


def _recording(path, rssi, label):
    """Minimal raw CSV + .meta.json sidecar, as app.log.record writes them."""
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_mono", "seq", "rssi_dbm", "noise_dbm", "channel"])
        w.writerows([i / HZ, i, r, -94, 36] for i, r in enumerate(rssi))
    path.with_suffix(".meta.json").write_text(json.dumps({"label": label}))
    return path


def test_constant_rssi_calibration_floors_activity_threshold():
    cal = calibrate.derive(np.full(300, -60.0), hz=HZ)    # quiet empty room, RSSI never moves
    assert cal["rolling_std_p95_db"] == 0
    assert cal["suggested_activity_std_db"] == 0.3


def test_constant_room_calibration_drives_meter_and_classifier(tmp_path, monkeypatch):
    monkeypatch.setattr(calibrate, "CAL", tmp_path / "calibration.json")
    monkeypatch.setattr(classifier, "CAL", tmp_path / "calibration.json")
    monkeypatch.setattr(classifier, "RULES", tmp_path / "rules.json")
    _recording(tmp_path / "still.csv", [-60 - (i % 9 == 0) for i in range(100)], "STILL")
    _recording(tmp_path / "walk.csv", [-60 + (6 if i % 2 else -6) for i in range(100)], "WALKING")
    monkeypatch.setattr(calibrate, "record", lambda hz, duration, meta, *a: _recording(
        tmp_path / "empty.csv", [-60] * int(hz * duration), "EMPTY"))

    cal = calibrate.run_calibration(duration=60, hz=HZ, room="t")
    assert any("constant" in w for w in cal["warnings"])
    assert cal["rules"].startswith("Rules re-fitted")

    meter = ActivityMeter(hz=HZ, calibration=cal)
    clf = LiveClassifier(HZ, json.loads((tmp_path / "rules.json").read_text()))
    for _ in range(20):
        act, state = meter.update(-60), clf.update(-60)
    assert act["level"] == "LOW" and state["state"] == "ABSENT"


# calibration.json / rules.json written before the floor existed can still hold 0.0
OLD_CAL = {"suggested_activity_std_db": 0.0, "suggested_mean_shift_db": 1.0, "baseline_mean_dbm": -60.0}
OLD_RULES = {"window_s": 3, "baseline_mean_dbm": -60.0, "presence_std_db": 0.0,
             "presence_shift_db": 1.0, "active_dE": 0.64}


def test_meter_tolerates_zero_threshold_from_old_calibration():
    m = ActivityMeter(hz=HZ, calibration=OLD_CAL)
    for _ in range(15):
        r = m.update(-60)
    assert r["level"] == "LOW" and r["threshold_db"] == 0.3


def test_classify_tolerates_zero_presence_threshold_from_old_rules():
    assert classify({"std": 0.0, "shift": 0.0, "dE": 0.0}, OLD_RULES)[0] == "ABSENT"
    assert classify({"std": 1.5, "shift": 0.0, "dE": 2.0}, OLD_RULES)[0] == "ACTIVE"
