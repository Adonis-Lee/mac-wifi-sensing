"""Record raw RSSI to data/raw/<name>.csv plus a .meta.json sidecar. Raw files are never modified.

Example: python -m app.log --hz 5 --duration 60 --room school --label TEST
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path

from app.backend import MacRSSIBackend, RssiSample

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
COLUMNS = [f.name for f in fields(RssiSample)]


def next_path(prefix: str = "mac_rssi") -> Path:
    RAW.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y_%m_%d")
    n = 1
    while (p := RAW / f"{prefix}_{day}_{n:03d}.csv").exists():
        n += 1
    return p


def record(hz: float, duration: float, meta: dict, on_sample=None, cancel=None) -> Path:
    """on_sample(n, count, sample) is called per sample; cancel() -> True stops early."""
    path = next_path()
    count = int(round(hz * duration))
    backend = MacRSSIBackend()
    first = last = None
    n = 0
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        print(f"Recording {duration:.0f}s @ {hz} Hz requested -> {path.name}")
        try:
            for s in backend.stream(hz, count):
                w.writerow(asdict(s))
                first = first or s
                last = s
                n += 1
                if on_sample:
                    on_sample(n, count, s)
                if cancel and cancel():
                    meta["note"] = (meta.get("note", "") + " [cancelled]").strip()
                    break
                if n % max(1, int(hz)) == 0:
                    print(f"\r  {n}/{count}  RSSI {s.rssi_dbm:4d} dBm  noise {s.noise_dbm} dBm  ch {s.channel}",
                          end="", flush=True)
        except KeyboardInterrupt:
            print("\n  interrupted; keeping partial file")
    print()
    actual = (n - 1) / (last.t_mono - first.t_mono) if n > 1 else 0.0
    meta.update(
        file=path.name, requested_hz=hz, actual_hz=round(actual, 3), samples=n,
        requested_duration_s=duration,
        duration_s=round(last.t_mono - first.t_mono, 3) if n > 1 else 0,
        start=first.timestamp if first else None, interface=first.interface if first else None,
        channel=first.channel if first else None, backend=backend.name,
        macos=platform.mac_ver()[0], machine=platform.machine(),
    )
    path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2))
    print(f"Requested rate: {hz} Hz\nActual rate:    {actual:.3f} Hz\nSamples:        {n}")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hz", type=float, default=5)
    ap.add_argument("--duration", type=float, default=60)
    ap.add_argument("--room", default="unknown")
    ap.add_argument("--label", default="UNLABELED", help="EMPTY, STILL, WALKING, ... or TEST")
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    path = record(a.hz, a.duration, {"room": a.room, "label": a.label, "note": a.note})
    print(f"Saved: {path}\nNext:  python -m app.quality {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
