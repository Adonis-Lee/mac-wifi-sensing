"""Rule-based state: ABSENT / PRESENT_STILL / ACTIVE from 3 s windows of real RSSI.

Thresholds are fitted from labelled recordings (`python -m app.classifier fit ...`) into
data/rules.json; nothing is hard-coded. Provisional: fitted on few home recordings, one subject.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, deque
from pathlib import Path

import numpy as np

from app.quality import load

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "data" / "rules.json"
CAL = ROOT / "data" / "calibration.json"
STATES = ("ABSENT", "PRESENT_STILL", "ACTIVE")
LABEL_TO_STATE = {"EMPTY": "ABSENT", "STILL": "PRESENT_STILL", "STILL_OFFLINE": "PRESENT_STILL",
                  "WALKING": "ACTIVE", "WALKING_LINK": "ACTIVE", "WALKING_ROOM": "ACTIVE",
                  "HAND_MOVEMENT": "ACTIVE", "SIT_DOWN": "ACTIVE", "STAND_UP": "ACTIVE"}


def window_features(win: np.ndarray, baseline: float) -> dict:
    return {"std": float(win.std(ddof=1)), "shift": float(abs(win.mean() - baseline)),
            "dE": float(np.mean(np.diff(win) ** 2))}


def windows(rssi: np.ndarray, w: int):
    for i in range(w, len(rssi) + 1):
        yield rssi[i - w:i]


def _split(a: list[float], b: list[float]) -> float:
    """Threshold between two classes: geometric mean of their medians (robust, scale-aware)."""
    return float(np.sqrt(max(np.median(a), 1e-3) * max(np.median(b), 1e-3)))


def fit(files: list[Path], skip_s: float = 5, window_s: float = 3) -> dict:
    cal = json.loads(CAL.read_text())
    feats: dict[str, list[dict]] = {s: [] for s in STATES}
    for p in files:
        label = json.loads(p.with_suffix(".meta.json").read_text())["label"]
        state = LABEL_TO_STATE[label]
        d = load(p)
        fs = (len(d["t"]) - 1) / (d["t"][-1] - d["t"][0])
        r = d["rssi"][int(skip_s * fs):]
        feats[state] += [window_features(x, cal["baseline_mean_dbm"]) for x in windows(r, int(window_s * fs))]
    rules = {
        "window_s": window_s, "baseline_mean_dbm": cal["baseline_mean_dbm"],
        # presence: from empty-room calibration
        "presence_std_db": cal["suggested_activity_std_db"],
        "presence_shift_db": cal["suggested_mean_shift_db"],
        # motion: separates STILL from ACTIVE windows
        "active_dE": _split([f["dE"] for f in feats["PRESENT_STILL"]], [f["dE"] for f in feats["ACTIVE"]]),
        "fitted_on": [p.name for p in files],
        "windows_per_state": {s: len(v) for s, v in feats.items()},
        "note": "provisional: few recordings, single subject/room; re-fit after proper experiments",
    }
    return rules


def classify(f: dict, rules: dict) -> tuple[str, float]:
    """Return (state, confidence 0..1). Confidence = margin from the deciding threshold."""
    p = max(f["std"] / rules["presence_std_db"], f["shift"] / rules["presence_shift_db"])
    if p <= 1:
        return "ABSENT", float(np.clip(1 - p, 0.05, 1) ** 0.5)
    # dE (sample-to-sample change) only: std also rises with slow drift while standing still
    m = f["dE"] / rules["active_dE"]
    if m > 1:
        return "ACTIVE", float(np.clip(1 - 1 / m, 0.05, 1) ** 0.5)
    return "PRESENT_STILL", float(np.clip(min(1 - 1 / p, 1 - m), 0.05, 1) ** 0.5)


class LiveClassifier:
    """Streaming wrapper with a short majority vote to suppress single-window flicker."""

    def __init__(self, hz: float, rules: dict, vote_s: float = 2.0):
        self.rules = rules
        self.win = deque(maxlen=max(3, int(rules["window_s"] * hz)))
        self.votes = deque(maxlen=max(1, int(vote_s * hz)))

    def update(self, rssi: float) -> dict | None:
        self.win.append(rssi)
        if len(self.win) < self.win.maxlen:
            return None
        f = window_features(np.asarray(self.win, float), self.rules["baseline_mean_dbm"])
        state, conf = classify(f, self.rules)
        self.votes.append((state, conf))
        top, n = Counter(s for s, _ in self.votes).most_common(1)[0]
        c = float(np.mean([c for s, c in self.votes if s == top])) * n / len(self.votes)
        return {"state": top, "confidence": c, "raw_state": state, **f}


def load_rules() -> dict | None:
    return json.loads(RULES.read_text()) if RULES.exists() else None


def evaluate(files: list[Path], rules: dict, skip_s: float = 5) -> None:
    for p in files:
        label = json.loads(p.with_suffix(".meta.json").read_text())["label"]
        d = load(p)
        fs = (len(d["t"]) - 1) / (d["t"][-1] - d["t"][0])
        lc = LiveClassifier(fs, rules)
        out = [o["state"] for x in d["rssi"][int(skip_s * fs):] if (o := lc.update(x))]
        cnt = Counter(out)
        acc = cnt[LABEL_TO_STATE[label]] / len(out)
        print(f"{p.name}  {label:13s} -> " + "  ".join(f"{s} {100 * cnt[s] / len(out):5.1f}%" for s in STATES)
              + f"   match {100 * acc:5.1f}%")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["fit", "eval"])
    ap.add_argument("files", nargs="+", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "fit":
        rules = fit(a.files)
        RULES.write_text(json.dumps(rules, indent=2))
        print(json.dumps({k: v for k, v in rules.items() if k != "fitted_on"}, indent=2))
    rules = load_rules()
    print("\nEvaluation (same files as fit = optimistic, not a test score):" if a.cmd == "fit" else "\nEvaluation:")
    evaluate(a.files, rules)


if __name__ == "__main__":
    main()
