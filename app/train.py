"""ML baseline (LogReg / RandomForest / SVM) with subject-independent evaluation.

Splits are by SUBJECT (whole recordings), never by window, so windows of one recording
never appear in both train and test. Needs >= 3 subjects:
  python -m app.train --test S05 --val S04
With fewer subjects it refuses rather than reporting a leaky score.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from app.classifier import LABEL_TO_STATE
from app.features import extract
from app.log import RAW
from app.quality import load

ROOT = Path(__file__).resolve().parent.parent
FEATURES = ["std", "var", "range", "mad", "iqr", "skew", "kurtosis", "deriv_energy",
            "ema_residual", "n_change_points", "motion_band_power", "total_power", "shift"]


def dataset(window_s: float = 5, step_s: float = 1, skip_s: float = 5, target: str = "state"):
    cal_p = ROOT / "data" / "calibration.json"
    baseline = json.loads(cal_p.read_text())["baseline_mean_dbm"] if cal_p.exists() else None
    X, y, groups, recs = [], [], [], []
    for meta_p in sorted(RAW.glob("*.meta.json")):
        meta = json.loads(meta_p.read_text())
        if "subject" not in meta or meta.get("label") not in LABEL_TO_STATE:
            continue  # only app.collect recordings carry a subject id
        d = load(meta_p.with_name(meta_p.name.replace(".meta.json", ".csv")))
        fs = (len(d["t"]) - 1) / (d["t"][-1] - d["t"][0])
        r = d["rssi"][int(skip_s * fs):]
        w, s = int(window_s * fs), max(1, int(step_s * fs))
        base = baseline if baseline is not None else float(np.median(r))
        for i in range(0, len(r) - w + 1, s):
            f = extract(r[i:i + w], fs, base)
            X.append([f[k] for k in FEATURES])
            y.append(LABEL_TO_STATE[meta["label"]] if target == "state" else meta["label"])
            groups.append(meta["subject"])
            recs.append(meta.get("exp_id", meta_p.stem))
    return np.array(X), np.array(y), np.array(groups), np.array(recs)


def models():
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC
    return {
        "logreg": make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced")),
        "random_forest": RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=0),
        "svm_rbf": make_pipeline(StandardScaler(), SVC(class_weight="balanced")),
    }


def report(name, split, y_true, y_pred, labels):
    from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
    p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, labels=labels, average="macro", zero_division=0)
    print(f"  {name:14s} {split:5s} acc {accuracy_score(y_true, y_pred):.3f}  "
          f"prec {p:.3f}  rec {r:.3f}  F1 {f1:.3f}")
    return confusion_matrix(y_true, y_pred, labels=labels)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--test", required=True, help="subject id held out for test")
    ap.add_argument("--val", required=True, help="subject id held out for validation")
    ap.add_argument("--target", choices=["state", "label"], default="state")
    a = ap.parse_args(argv)
    X, y, g, _ = dataset(target=a.target)
    subjects = sorted(set(g))
    print(f"windows {len(y)}  subjects {subjects}  classes {sorted(set(y))}")
    if len(subjects) < 3 or a.test not in subjects or a.val not in subjects or a.test == a.val:
        raise SystemExit("Need >= 3 distinct subjects incl. --test and --val (recorded with app.collect). "
                         "Not training: a split within one subject would leak.")
    tr, va, te = ~np.isin(g, [a.test, a.val]), g == a.val, g == a.test
    labels = sorted(set(y))
    for name, m in models().items():
        m.fit(X[tr], y[tr])
        report(name, "val", y[va], m.predict(X[va]), labels)
        cm = report(name, "test", y[te], m.predict(X[te]), labels)
        print("    confusion (rows=true, cols=pred):", labels)
        for lab, row in zip(labels, cm):
            print(f"    {lab:14s} {row.tolist()}")


if __name__ == "__main__":
    main()
