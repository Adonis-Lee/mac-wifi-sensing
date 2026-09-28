"""Compare recordings: stats table + PNG (timeline, histogram, Welch PSD, rolling std).

Example: python -m app.report data/raw/a.csv data/raw/b.csv --skip 10 --out data/processed/report.png
Frequency axes use each file's measured sample rate. Raw files are only read.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import welch

from app.calibrate import rolling_std
from app.quality import load

ROOT = Path(__file__).resolve().parent.parent
MOTION_BAND = (0.3, 2.0)  # Hz; body motion band, capped by the ~2.5 Hz Nyquist at 5 Hz


def features(rssi: np.ndarray, fs: float, cal: dict | None) -> dict:
    w = max(3, int(round(3 * fs)))
    rs = rolling_std(rssi, w)
    f, p = welch(rssi - rssi.mean(), fs=fs, nperseg=min(len(rssi), int(20 * fs)))
    band = (f >= MOTION_BAND[0]) & (f <= MOTION_BAND[1])
    out = {
        "mean": rssi.mean(), "std": rssi.std(ddof=1), "range": np.ptp(rssi),
        "deriv_energy": float(np.mean(np.diff(rssi) ** 2)),
        "rolling_std_med": float(np.median(rs)),
        "motion_band_power": float(np.trapezoid(p[band], f[band])),
        "psd": (f, p), "rolling_std": rs,
    }
    if cal:
        mu = np.convolve(rssi, np.ones(w) / w, "valid")
        act = (rs > cal["suggested_activity_std_db"]) | \
              (np.abs(mu - cal["baseline_mean_dbm"]) > cal["suggested_mean_shift_db"])
        out["over_threshold_pct"] = 100 * act.mean()
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--skip", type=float, default=0, help="seconds to drop at start of each file")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "processed" / "report.png")
    a = ap.parse_args(argv)
    cal_p = ROOT / "data" / "calibration.json"
    cal = json.loads(cal_p.read_text()) if cal_p.exists() else None

    fig, ax = plt.subplots(2, 2, figsize=(14, 8))
    print(f"{'label':14s} {'n':>4s} {'mean':>7s} {'std':>5s} {'range':>5s} {'dE':>5s} "
          f"{'rstd':>5s} {'band':>6s} {'>thr%':>6s}")
    for p in a.files:
        meta_p = p.with_suffix(".meta.json")
        label = json.loads(meta_p.read_text()).get("label", p.stem) if meta_p.exists() else p.stem
        d = load(p)
        fs = (len(d["t"]) - 1) / (d["t"][-1] - d["t"][0])
        keep = d["t"] - d["t"][0] >= a.skip
        t, r = d["t"][keep] - d["t"][keep][0], d["rssi"][keep]
        ft = features(r, fs, cal)
        print(f"{label:14s} {len(r):4d} {ft['mean']:7.2f} {ft['std']:5.2f} {ft['range']:5.0f} "
              f"{ft['deriv_energy']:5.2f} {ft['rolling_std_med']:5.2f} {ft['motion_band_power']:6.3f} "
              f"{ft.get('over_threshold_pct', float('nan')):6.1f}")
        ax[0, 0].plot(t, r, lw=1, label=label)
        ax[0, 1].hist(r, bins=np.arange(r.min() - 0.5, r.max() + 1.5), alpha=0.5, label=label)
        ax[1, 0].semilogy(*ft["psd"], label=label)
        ax[1, 1].plot(t[len(t) - len(ft["rolling_std"]):], ft["rolling_std"], lw=1, label=label)
    if cal:
        ax[0, 0].axhline(cal["baseline_mean_dbm"], ls="--", c="k", lw=0.8, label="empty baseline")
        ax[1, 1].axhline(cal["suggested_activity_std_db"], ls="--", c="k", lw=0.8, label="threshold")
    ax[1, 0].axvspan(*MOTION_BAND, color="grey", alpha=0.15, label="motion band")
    for x, title, xl, yl in [(ax[0, 0], "RSSI timeline", "s", "dBm"), (ax[0, 1], "Histogram", "dBm", "count"),
                             (ax[1, 0], "Welch PSD (measured fs)", "Hz", "dB²/Hz"),
                             (ax[1, 1], "Rolling std (3 s)", "s", "dB")]:
        x.set_title(title); x.set_xlabel(xl); x.set_ylabel(yl); x.grid(alpha=0.3); x.legend(fontsize=8)
    fig.suptitle("MacBook RSSI-only · single link · not CSI", fontsize=11)
    fig.tight_layout()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.out, dpi=110)
    print(f"Saved {a.out}")


if __name__ == "__main__":
    main()
