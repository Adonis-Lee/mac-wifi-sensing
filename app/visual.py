"""3D RF activity view in the browser, driven by real CoreWLAN RSSI (Server-Sent Events).

Example: python -m app.visual --hz 5   then open http://127.0.0.1:8765
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.activity import ActivityMeter, load_calibration
from app.backend import MacRSSIBackend

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


def collector(hub: Hub, hz: float) -> None:
    meter = ActivityMeter(hz, calibration=load_calibration())
    try:
        for s in MacRSSIBackend().stream(hz):
            t0 = time.perf_counter()
            act = meter.update(s.rssi_dbm) if s.associated else None
            hub.publish({**asdict(s), "associated": s.associated, "activity": act,
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
    a = ap.parse_args(argv)
    hub = Hub()
    threading.Thread(target=collector, args=(hub, a.hz), daemon=True).start()
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
