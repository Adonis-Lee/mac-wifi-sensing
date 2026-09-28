"""Dataset collector with experiment IDs (EXP001, EXP002, ...) and full metadata.

Example: python -m app.collect            (interactive prompts)
         python -m app.collect --subject S01 --cls WALKING --room home --distance 2.5 \
                --orientation lid-toward-router --trial 1 --duration 60 --yes
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.log import RAW, record

CLASSES = ["EMPTY", "STILL", "STILL_OFFLINE", "WALKING", "WALKING_LINK", "WALKING_ROOM",
           "HAND_MOVEMENT", "SIT_DOWN", "STAND_UP"]
REGISTRY = RAW.parent / "experiments.jsonl"


def next_exp_id() -> str:
    n = 0
    if REGISTRY.exists():
        for line in REGISTRY.read_text().splitlines():
            if line.strip():
                n = max(n, int(json.loads(line)["exp_id"][3:]))
    return f"EXP{n + 1:03d}"


def ask(prompt: str, default: str | None = None, choices: list[str] | None = None) -> str:
    hint = f" [{default}]" if default else ""
    if choices:
        print("  " + ", ".join(choices))
    while True:
        v = input(f"{prompt}{hint}: ").strip() or (default or "")
        if v and (not choices or v.upper() in choices):
            return v.upper() if choices else v


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    for k in ["subject", "cls", "room", "distance", "orientation", "trial"]:
        ap.add_argument(f"--{k}")
    ap.add_argument("--duration", type=float)
    ap.add_argument("--hz", type=float, default=5)
    ap.add_argument("--yes", action="store_true", help="skip the ENTER prompt")
    a = ap.parse_args(argv)

    meta = {
        "subject": a.subject or ask("Subject ID", "S01"),
        "label": (a.cls or ask("Class", choices=CLASSES)).upper(),
        "room": a.room or ask("Room", "home"),
        "distance_m": a.distance or ask("Router-Mac distance (m)", "unknown"),
        "orientation": a.orientation or ask("Mac orientation", "unchanged"),
        "trial": a.trial or ask("Trial", "1"),
    }
    if meta["label"] not in CLASSES:
        print(f"Unknown class {meta['label']}; choose from {CLASSES}")
        return 2
    duration = a.duration or float(ask("Duration (s)", "60"))
    exp_id = next_exp_id()
    meta.update(exp_id=exp_id, note=f"{exp_id} via app.collect")
    print(f"\n{exp_id}: {meta['label']}  subject={meta['subject']}  trial={meta['trial']}  {duration:.0f}s")
    if not a.yes:
        input("[ENTER] Start")
    path = record(a.hz, duration, meta)
    entry = json.loads(path.with_suffix(".meta.json").read_text())
    with REGISTRY.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"\a{exp_id} done -> {path.name} (registered in {REGISTRY.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
