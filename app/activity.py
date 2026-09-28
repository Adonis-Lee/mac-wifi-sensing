"""RF activity score from real RSSI. Not presence, not location.

With a calibration (data/calibration.json from `python -m app.calibrate`), levels come from
the empty-room baseline:
  ratio = rolling std (3 s) / suggested_activity_std_db, plus mean shift vs baseline.
Without one, it falls back to a RELATIVE score against the quietest recent period.
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path

import numpy as np

CAL = Path(__file__).resolve().parent.parent / "data" / "calibration.json"


def load_calibration(path: Path = CAL) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


class ActivityMeter:
    def __init__(self, hz: float, short_s: float = 3.0, history_s: float = 120.0,
                 floor_db: float = 0.3, calibration: dict | None = None):
        self.win = deque(maxlen=max(3, int(short_s * hz)))
        self.stds = deque(maxlen=max(10, int(history_s * hz)))
        self.floor_db = floor_db  # 1 dB RSSI quantization makes std < ~0.3 dB meaningless
        self.cal = calibration

    def update(self, rssi: float) -> dict:
        self.win.append(rssi)
        arr = np.asarray(self.win, float)
        std = float(arr.std(ddof=1)) if len(arr) > 2 else 0.0
        d_energy = float(np.mean(np.diff(arr) ** 2)) if len(arr) > 2 else 0.0
        self.stds.append(std)
        out = {"std_db": std, "deriv_energy": d_energy}

        if self.cal:
            thr = self.cal["suggested_activity_std_db"]
            shift = abs(float(arr.mean()) - self.cal["baseline_mean_dbm"])
            ratio = max(std / thr, shift / self.cal["suggested_mean_shift_db"])
            warm = len(arr) == self.win.maxlen
            out.update(mode="calibrated", threshold_db=thr, mean_shift_db=shift)
        else:
            thr = max(self.floor_db, float(np.percentile(self.stds, 20)))
            ratio = std / thr
            warm = len(self.stds) >= self.stds.maxlen // 4
            out.update(mode="relative", threshold_db=thr, mean_shift_db=None)

        # calibrated: ratio 1 == empty-room threshold. relative: ratio 1 == quiet floor.
        hi, mid = (2.0, 1.0) if self.cal else (3.0, 1.8)
        level = "WARMUP" if not warm else "HIGH" if ratio > hi else "MEDIUM" if ratio > mid else "LOW"
        lo = 0.5 if self.cal else 1.0
        intensity = float(np.clip(np.log(max(ratio / lo, 1.0)) / np.log(6.0), 0, 1))
        out.update(ratio=ratio, intensity=intensity, level=level)
        return out
