"""Live RSSI graph. Collector runs in a thread so the GUI never blocks on CoreWLAN.

Example: python -m app.live --hz 5 --window 60
"""
from __future__ import annotations

import argparse
import queue
import threading
from collections import deque

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

from app.backend import MacRSSIBackend


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hz", type=float, default=5)
    ap.add_argument("--window", type=float, default=60, help="seconds shown")
    a = ap.parse_args(argv)

    q: queue.Queue = queue.Queue()
    backend = MacRSSIBackend()
    stop = threading.Event()

    def collect():
        try:
            for s in backend.stream(a.hz):
                q.put(s)
                if stop.is_set():
                    break
        except Exception as e:  # surfaced in the plot title, not swallowed
            q.put(e)

    threading.Thread(target=collect, daemon=True).start()

    maxlen = int(a.window * a.hz * 1.2)
    t, rssi, noise = deque(maxlen=maxlen), deque(maxlen=maxlen), deque(maxlen=maxlen)
    t0 = [None]
    err = [None]

    fig, ax = plt.subplots(figsize=(10, 4.5))
    (l_rssi,) = ax.plot([], [], lw=1.4, label="RSSI (dBm)")
    (l_noise,) = ax.plot([], [], lw=1, alpha=0.6, label="Noise (dBm)")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("dBm")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left")
    info = ax.text(0.99, 0.02, "", transform=ax.transAxes, ha="right", va="bottom",
                   family="monospace", fontsize=9)

    def update(_):
        while True:
            try:
                s = q.get_nowait()
            except queue.Empty:
                break
            if isinstance(s, Exception):
                err[0] = s
                continue
            t0[0] = t0[0] if t0[0] is not None else s.t_mono
            t.append(s.t_mono - t0[0])
            rssi.append(s.rssi_dbm if s.associated else float("nan"))
            noise.append(s.noise_dbm if s.associated else float("nan"))
            info.set_text(f"ch {s.channel} {s.band} {s.phy_mode}  read {s.read_ms:.1f} ms")
        if len(t) > 1 and any(x == x for x in rssi):  # x == x filters NaN (not associated)
            l_rssi.set_data(t, rssi)
            l_noise.set_data(t, noise)
            ax.set_xlim(max(0, t[-1] - a.window), max(a.window, t[-1]))
            lo = min(x for x in list(rssi) + list(noise) if x == x)
            hi = max(x for x in rssi if x == x)
            ax.set_ylim(lo - 3, hi + 3)
            recent = [x for x in t if x >= t[-1] - 5]
            rate = (len(recent) - 1) / (recent[-1] - recent[0]) if len(recent) > 1 else 0.0
            ax.set_title(("ERROR: " + str(err[0])) if err[0] else
                         f"Live RSSI  {rssi[-1]:.0f} dBm   actual {rate:.2f} Hz (5 s) / requested {a.hz} Hz")
        return l_rssi, l_noise, info

    _anim = FuncAnimation(fig, update, interval=100, cache_frame_data=False)
    try:
        plt.show()
    finally:
        stop.set()
        backend.close()


if __name__ == "__main__":
    main()
