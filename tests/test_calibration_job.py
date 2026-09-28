import time

from app import calibrate
from app.visual import CalibrationJob, Hub


def _events(hub):
    import json
    return [json.loads(e) for e in hub.events]


def test_job_reports_progress_and_result(monkeypatch):
    def fake_run(duration, hz, room, on_sample=None, cancel=None):
        for n in range(1, 4):
            on_sample(n, 3, type("S", (), {"rssi_dbm": -70})())
        return {"source_file": "x.csv", "baseline_mean_dbm": -70.0}
    monkeypatch.setattr(calibrate, "run_calibration", fake_run)
    hub = Hub()
    job = CalibrationJob(hub, hz=5)
    assert job.start(duration=30, delay=0, room="t")
    job.thread.join(5)
    phases = [e["phase"] for e in _events(hub)]
    assert phases[0] == "recording" and phases[-1] == "done"


def test_cancel_during_countdown_writes_nothing(monkeypatch):
    called = []
    monkeypatch.setattr(calibrate, "run_calibration", lambda *a, **k: called.append(1))
    hub = Hub()
    job = CalibrationJob(hub, hz=5)
    job.start(duration=30, delay=3, room="t")
    time.sleep(0.2)
    job.cancel()
    job.thread.join(5)
    assert not called and _events(hub)[-1]["phase"] == "cancelled"
