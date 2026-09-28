"""3D RF activity view in the browser, driven by real CoreWLAN RSSI (Server-Sent Events).

Live:   python -m app.visual --hz 5
Replay: python -m app.visual --replay data/raw/<file>.csv   (recorded real data, original timing)
"""
from __future__ import annotations

import argparse
import os
import resource
import csv
import json
import threading
import time
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.activity import CAL as CAL_PATH, ActivityMeter, load_calibration
from app.backend import MacRSSIBackend, RssiSample
from app.classifier import RULES as RULES_PATH, LiveClassifier, load_rules

WEB = Path(__file__).resolve().parent.parent / "web" / "index.html"


class Hub:
    """Latest events for SSE clients; the collector never waits on the browser."""

    def __init__(self):
        self.cond = threading.Condition()
        self.events: list[str] = []
        self.n = 0

    def publish(self, payload: dict) -> None:
        with self.cond:
            self.events.append(json.dumps(payload))
            self.events = self.events[-50:]
            self.n += 1
            self.cond.notify_all()


def replay_stream(path: Path, speed: float = 1.0):
    """Yield recorded samples with their original spacing, looping forever."""
    with path.open() as f:
        rows = list(csv.DictReader(f))
    while True:
        prev = None
        for r in rows:
            s = RssiSample(timestamp=r["timestamp"], t_mono=float(r["t_mono"]), seq=int(r["seq"]),
                           interface=r["interface"], rssi_dbm=int(r["rssi_dbm"]), noise_dbm=int(r["noise_dbm"]),
                           channel=int(r["channel"]) if r["channel"] else None, band=r["band"],
                           phy_mode=r["phy_mode"], tx_rate_mbps=float(r["tx_rate_mbps"]),
                           ssid=r["ssid"] or None, read_ms=float(r["read_ms"]))
            if prev is not None:
                time.sleep(max(0.0, (s.t_mono - prev) / speed))
            prev = s.t_mono
            yield s


def collector(hub: Hub, hz: float, replay: Path | None = None) -> None:
    meter = ActivityMeter(hz, calibration=load_calibration())
    rules = load_rules()
    clf = LiveClassifier(hz, rules) if rules else None
    files_stamp = tuple(p.stat().st_mtime if p.exists() else 0 for p in (CAL_PATH, RULES_PATH))
    c0 = os.times()
    perf = {"t": time.monotonic(), "cpu": c0.user + c0.system, "cpu_pct": 0.0, "rss_mb": 0.0}
    try:
        source = replay_stream(replay) if replay else MacRSSIBackend().stream(hz)
        for s in source:
            t0 = time.perf_counter()
            stamp = tuple(p.stat().st_mtime if p.exists() else 0 for p in (CAL_PATH, RULES_PATH))
            if stamp != files_stamp:  # calibration/rules changed on disk -> hot reload
                files_stamp = stamp
                meter = ActivityMeter(hz, calibration=load_calibration())
                rules = load_rules()
                clf = LiveClassifier(hz, rules) if rules else None
            act = meter.update(s.rssi_dbm) if s.associated else None
            state = clf.update(s.rssi_dbm) if clf and s.associated else None
            now = time.monotonic()
            cpu = os.times()
            if now - perf["t"] >= 2:
                perf["cpu_pct"] = 100 * (cpu.user + cpu.system - perf["cpu"]) / (now - perf["t"])
                perf.update(t=now, cpu=cpu.user + cpu.system)
            perf["rss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20  # bytes on macOS
            hub.publish({**asdict(s), "perf": dict(cpu_pct=perf["cpu_pct"], rss_mb=perf["rss_mb"]), "associated": s.associated, "activity": act, "state": state,
                         "source": f"REPLAY {replay.name}" if replay else "LIVE",
                         "proc_ms": (time.perf_counter() - t0) * 1000})
    except Exception as e:
        hub.publish({"error": str(e)})


def handler_for(hub: Hub):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/":
                body = WEB.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                seen = hub.n
                try:
                    while True:
                        with hub.cond:
                            hub.cond.wait_for(lambda: hub.n > seen, timeout=15)
                            new = hub.events[-min(hub.n - seen, len(hub.events)):] if hub.n > seen else []
                            seen = hub.n
                        for e in new:
                            self.wfile.write(f"data: {e}\n\n".encode())
                        if not new:
                            self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
            else:
                self.send_error(404)
    return H


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hz", type=float, default=5)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--replay", type=Path, help="play a recorded CSV instead of live Wi-Fi")
    a = ap.parse_args(argv)
    hub = Hub()
    threading.Thread(target=collector, args=(hub, a.hz, a.replay), daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), handler_for(hub))
    url = f"http://127.0.0.1:{a.port}"
    print(f"RF activity view: {url}  (Ctrl-C to stop)")
    if not a.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
