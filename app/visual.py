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
        self.last_link: tuple[int, int] | None = None

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


def scanner(hub: Hub, period_s: float = 5.0) -> None:
    """Nearby networks every few seconds (anonymous without Location Services)."""
    import subprocess
    from app.backend import HELPER
    while True:
        try:
            out = subprocess.run([str(HELPER), "--scan-once"], capture_output=True, text=True, timeout=15)
            if out.returncode == 0:
                hub.publish({"type": "scan", **json.loads(out.stdout)})
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        time.sleep(period_s)


def devices_loop(hub: Hub, lan: bool, router_distance: float | None, period_s: float = 3.0) -> None:
    from app.devices import BleReader, lan_devices, wall_estimate
    ble = BleReader()
    ble.start()
    while True:
        payload = {"type": "devices", "ble": ble.read()}
        if lan:
            payload["lan"] = lan_devices()
        if router_distance and hub.last_link:
            rssi, ch = hub.last_link
            payload["wall"] = wall_estimate(rssi, ch, router_distance)
        hub.publish(payload)
        time.sleep(period_s)


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
            if s.associated and s.channel:
                hub.last_link = (s.rssi_dbm, s.channel)
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


class CalibrationJob:
    """One calibration at a time, driven from the web UI. Publishes {"type": "calib", ...} events."""

    def __init__(self, hub: Hub, hz: float):
        self.hub, self.hz = hub, hz
        self.thread: threading.Thread | None = None
        self.cancelled = False

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self, duration: float, delay: float, room: str) -> bool:
        if self.running:
            return False
        self.cancelled = False
        self.thread = threading.Thread(target=self._run, args=(duration, delay, room), daemon=True)
        self.thread.start()
        return True

    def cancel(self) -> None:
        self.cancelled = True

    def _run(self, duration: float, delay: float, room: str) -> None:
        from app.calibrate import run_calibration
        pub = lambda **k: self.hub.publish({"type": "calib", **k})
        try:
            for left in range(int(delay), 0, -1):
                if self.cancelled:
                    return pub(phase="cancelled")
                pub(phase="countdown", seconds=left)
                time.sleep(1)
            pub(phase="recording", n=0, count=int(duration * self.hz))
            last = [0.0]

            def on_sample(n, count, s):
                if time.monotonic() - last[0] > 0.5 or n == count:
                    last[0] = time.monotonic()
                    pub(phase="recording", n=n, count=count, rssi=s.rssi_dbm)

            res = run_calibration(duration, self.hz, room, on_sample, lambda: self.cancelled)
            pub(phase="cancelled" if res.get("cancelled") else "done", result=res)
        except Exception as e:  # surfaced in the UI, not swallowed
            pub(phase="error", message=str(e))


def handler_for(hub: Hub, job: "CalibrationJob | None" = None):
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

        def _json(self, code: int, obj: dict) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            # local UI only: same-origin + JSON body (a cross-site form post cannot set this content type
            # without a CORS preflight, which this server never answers)
            origin = self.headers.get("Origin", "")
            host = self.headers.get("Host", "")
            if (origin and origin != f"http://{host}") or not host.startswith(("127.0.0.1", "localhost")) \
                    or not self.headers.get("Content-Type", "").startswith("application/json"):
                return self._json(403, {"error": "forbidden"})
            if job is None:
                return self._json(409, {"error": "calibration unavailable in replay mode"})
            try:
                n = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(min(n, 4096)) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return self._json(400, {"error": "bad json"})
            if self.path == "/api/calibrate":
                duration = float(body.get("duration", 60))
                delay = float(body.get("delay", 10))
                room = str(body.get("room", "home"))[:40]
                if not (20 <= duration <= 300 and 0 <= delay <= 60):
                    return self._json(400, {"error": "duration 20-300 s, delay 0-60 s"})
                ok = job.start(duration, delay, room)
                return self._json(200 if ok else 409, {"started": ok})
            if self.path == "/api/calibrate/cancel":
                job.cancel()
                return self._json(200, {"cancelled": True})
            self._json(404, {"error": "not found"})
    return H


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hz", type=float, default=5)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--replay", type=Path, help="play a recorded CSV instead of live Wi-Fi")
    ap.add_argument("--lan", action="store_true",
                    help="list devices from this Mac's ARP cache (use only on your own network)")
    ap.add_argument("--router-distance", type=float, metavar="M",
                    help="measured Mac-router distance in metres -> excess path-loss estimate")
    a = ap.parse_args(argv)
    hub = Hub()
    threading.Thread(target=collector, args=(hub, a.hz, a.replay), daemon=True).start()
    if not a.replay:
        threading.Thread(target=scanner, args=(hub,), daemon=True).start()
        threading.Thread(target=devices_loop, args=(hub, a.lan, a.router_distance), daemon=True).start()
    job = None if a.replay else CalibrationJob(hub, a.hz)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), handler_for(hub, job))
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
