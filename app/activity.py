"""Uncalibrated RF activity score from real RSSI. Replaced by calibrated thresholds in M2.

score = rolling std (short window) / robust noise floor (low percentile of past rolling stds).
It is RELATIVE: 1.0 means "as quiet as the quietest recent period". Not presence, not location.
"""
from __future__ import annotations

from collections import deque

import numpy as np


class ActivityMeter:
    def __init__(self, hz: float, short_s: float = 3.0, history_s: float = 120.0, floor_db: float = 0.3):
        self.win = deque(maxlen=max(3, int(short_s * hz)))
        self.stds = deque(maxlen=max(10, int(history_s * hz)))
        self.floor_db = floor_db  # 1 dB RSSI quantization makes std < ~0.3 dB meaningless

    def update(self, rssi: float) -> dict:
        self.win.append(rssi)
        arr = np.asarray(self.win, float)
        std = float(arr.std(ddof=1)) if len(arr) > 2 else 0.0
        d_energy = float(np.mean(np.diff(arr) ** 2)) if len(arr) > 2 else 0.0
        self.stds.append(std)
        floor = max(self.floor_db, float(np.percentile(self.stds, 20)))
        ratio = std / floor
        warm = len(self.stds) >= self.stds.maxlen // 4
        level = "WARMUP" if not warm else "HIGH" if ratio > 3 else "MEDIUM" if ratio > 1.8 else "LOW"
        # 0..1 for the renderer, log-scaled so ratio 1 -> 0, ratio 6 -> 1
        intensity = float(np.clip(np.log(max(ratio, 1.0)) / np.log(6.0), 0, 1))
        return {"std_db": std, "deriv_energy": d_energy, "floor_db": floor,
                "ratio": ratio, "intensity": intensity, "level": level}
