"""Empty-room calibration: records a baseline and derives thresholds from it (nothing hard-coded).

Example: python -m app.calibrate --duration 60 --room home
Writes data/raw/<file>.csv (label=EMPTY) and data/calibration.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from app.log import record
from app.quality import analyze, load, warnings

CAL = Path(__file__).resolve().parent.parent / "data" / "calibration.json"


def rolling_std(x: np.ndarray, w: int) -> np.ndarray:
    return np.array([x[i - w:i].std(ddof=1) for i in range(w, len(x) + 1)])


def derive(rssi: np.ndarray, hz: float, window_s: float = 3.0) -> dict:
    w = max(3, int(round(window_s * hz)))
    rs = rolling_std(rssi, w)
    return {
        "window_s": window_s,
        "baseline_mean_dbm": float(rssi.mean()),
        "baseline_std_db": float(rssi.std(ddof=1)),
        "rolling_std_p50_db": float(np.percentile(rs, 50)),
        "rolling_std_p95_db": float(np.percentile(rs, 95)),
        "rolling_std_max_db": float(rs.max()),
        # candidate thresholds; validated against STILL / WALKING recordings in the next step
        "suggested_activity_std_db": float(np.percentile(rs, 95) * 1.5),
        "suggested_mean_shift_db": float(max(1.0, 3 * rssi.std(ddof=1))),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--duration", type=float, default=60)
    ap.add_argument("--hz", type=float, default=5)
    ap.add_argument("--room", default="home")
    ap.add_argument("--delay", type=float, default=10, help="seconds to leave the room before recording")
    a = ap.parse_args(argv)

    print("=" * 36 + "\nMAC WI-FI CALIBRATION\nKeep environment empty. Do not move the MacBook.")
    for s in range(int(a.delay), 0, -1):
        print(f"\r  leave the room... starting in {s:2d}s", end="", flush=True)
        time.sleep(1)
    print()
    path = record(a.hz, a.duration, {"room": a.room, "label": "EMPTY", "note": "calibration"})
    d = load(path)
    q = analyze(d, a.hz)
    cal = {"source_file": path.name, "room": a.room, "actual_hz": q.actual_hz, **derive(d["rssi"], q.actual_hz)}
    CAL.write_text(json.dumps(cal, indent=2))
    print("\a" + "=" * 36)
    print(f"Baseline RSSI:        {cal['baseline_mean_dbm']:.2f} dBm")
    print(f"Std:                  {cal['baseline_std_db']:.3f} dB")
    print(f"Rolling std p95 (3s): {cal['rolling_std_p95_db']:.3f} dB")
    print(f"Suggested activity threshold (rolling std): {cal['suggested_activity_std_db']:.3f} dB")
    print(f"Suggested mean-shift threshold:             {cal['suggested_mean_shift_db']:.2f} dB")
    for w in warnings(q):
        print("WARN", w)
    print(f"Saved {CAL}")
    # re-fit rules: presence from this calibration, motion threshold from labelled STILL/ACTIVE recordings
    from app.classifier import LABEL_TO_STATE, RULES, fit
    raw = path.parent
    labelled = [p for p in sorted(raw.glob("*.csv")) if p != path and p.with_suffix(".meta.json").exists()
                and LABEL_TO_STATE.get(json.loads(p.with_suffix(".meta.json").read_text()).get("label"))
                in ("PRESENT_STILL", "ACTIVE")]
    states = {LABEL_TO_STATE[json.loads(p.with_suffix(".meta.json").read_text())["label"]] for p in labelled}
    if states == {"PRESENT_STILL", "ACTIVE"}:
        RULES.write_text(json.dumps(fit([path, *labelled]), indent=2))
        print(f"Rules re-fitted ({len(labelled)} labelled recordings) -> {RULES.name}. Live view picks it up.")
    else:
        print("No STILL + ACTIVE recordings yet; rules not fitted (live view shows activity only).")
    print("=" * 36)
    return 0


if __name__ == "__main__":
    sys.exit(main())
