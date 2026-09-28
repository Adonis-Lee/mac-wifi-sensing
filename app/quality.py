"""Data quality report for a raw RSSI CSV.

Example: python -m app.quality data/raw/mac_rssi_2026_09_28_001.csv
"""
from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

RSSI_VALID = (-100, -1)  # dBm range treated as physically plausible for a link


@dataclass
class Quality:
    samples: int
    valid: int
    zero_rssi: int
    invalid: int
    duplicate_seq: int
    missing: int             # gaps inferred from timestamps > 1.5 * median interval
    requested_hz: float | None
    actual_hz: float
    dt_median_ms: float
    dt_max_ms: float
    mean: float
    std: float
    var: float
    min: float
    max: float
    median: float
    mad: float
    unique_values: int
    channel_changes: int
    constant: bool


def load(path: Path) -> dict[str, np.ndarray]:
    with path.open() as f:
        rows = list(csv.DictReader(f))
    return {
        "t": np.array([float(r["t_mono"]) for r in rows]),
        "seq": np.array([int(r["seq"]) for r in rows]),
        "rssi": np.array([float(r["rssi_dbm"]) for r in rows]),
        "noise": np.array([float(r["noise_dbm"]) for r in rows]),
        "channel": np.array([r["channel"] for r in rows]),
    }


def analyze(d: dict[str, np.ndarray], requested_hz: float | None = None) -> Quality:
    t, rssi = d["t"], d["rssi"]
    n = len(rssi)
    if n < 2:
        raise ValueError(f"need at least 2 samples, got {n}")
    zero = rssi == 0
    valid = (rssi >= RSSI_VALID[0]) & (rssi <= RSSI_VALID[1])
    v = rssi[valid]
    dt = np.diff(t)
    med_dt = float(np.median(dt))
    gaps = dt[dt > 1.5 * med_dt]
    missing = int(np.sum(np.round(gaps / med_dt) - 1)) if len(gaps) else 0
    med = float(np.median(v)) if len(v) else float("nan")
    ch = d["channel"]
    return Quality(
        samples=n, valid=int(valid.sum()), zero_rssi=int(zero.sum()),
        invalid=int((~valid & ~zero).sum()),
        duplicate_seq=n - len(np.unique(d["seq"])), missing=missing,
        requested_hz=requested_hz, actual_hz=(n - 1) / (t[-1] - t[0]),
        dt_median_ms=med_dt * 1000, dt_max_ms=float(dt.max()) * 1000,
        mean=float(v.mean()), std=float(v.std(ddof=1)) if len(v) > 1 else 0.0,
        var=float(v.var(ddof=1)) if len(v) > 1 else 0.0,
        min=float(v.min()), max=float(v.max()), median=med,
        mad=float(np.median(np.abs(v - med))), unique_values=len(np.unique(v)),
        channel_changes=int(np.sum(ch[1:] != ch[:-1])),
        constant=len(np.unique(v)) == 1,
    )


def warnings(q: Quality) -> list[str]:
    w = []
    if q.constant:
        w.append("RSSI is constant: no variation observed. Not evidence of sensing; verify physically.")
    if q.zero_rssi:
        w.append(f"{q.zero_rssi} samples with RSSI=0 (interface not associated at that moment).")
    if q.channel_changes:
        w.append(f"{q.channel_changes} channel change(s): roaming/steering — segment before analysis.")
    if q.requested_hz and q.actual_hz < 0.9 * q.requested_hz:
        w.append(f"Actual rate {q.actual_hz:.2f} Hz is <90% of requested {q.requested_hz} Hz.")
    if q.missing:
        w.append(f"{q.missing} samples estimated missing from timing gaps (max dt {q.dt_max_ms:.0f} ms).")
    return w


def report(path: Path) -> str:
    import json
    meta_p = path.with_suffix(".meta.json")
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    q = analyze(load(path), meta.get("requested_hz"))
    lines = [
        "=" * 44, f"DATA QUALITY  {path.name}",
        f"label={meta.get('label', '?')}  room={meta.get('room', '?')}", "-" * 44,
        f"samples          {q.samples}  (valid {q.valid}, zero {q.zero_rssi}, invalid {q.invalid})",
        f"duplicates       {q.duplicate_seq}",
        f"missing (est.)   {q.missing}",
        f"rate             requested {q.requested_hz} Hz, actual {q.actual_hz:.3f} Hz",
        f"interval         median {q.dt_median_ms:.1f} ms, max {q.dt_max_ms:.1f} ms",
        f"mean / median    {q.mean:.2f} / {q.median:.2f} dBm",
        f"std / var        {q.std:.3f} dB / {q.var:.3f} dB^2",
        f"MAD              {q.mad:.2f} dB",
        f"min / max        {q.min:.0f} / {q.max:.0f} dBm  (range {q.max - q.min:.0f} dB, {q.unique_values} distinct)",
        f"channel changes  {q.channel_changes}",
    ]
    ws = warnings(q)
    lines += ["-" * 44] + [f"WARN  {x}" for x in ws] if ws else ["-" * 44, "No quality warnings."]
    lines.append("=" * 44)
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(report(Path(sys.argv[1])))
