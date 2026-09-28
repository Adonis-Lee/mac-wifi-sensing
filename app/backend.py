"""Sensing backends. Only MacRSSIBackend is implemented (RSSI-only, not CSI)."""
from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

HELPER = Path(__file__).resolve().parent.parent / "bin" / "mac_wifi_reader"


@dataclass(frozen=True)
class RssiSample:
    timestamp: str          # ISO-8601 UTC wall clock
    t_mono: float           # monotonic seconds (system uptime), used for rate math
    seq: int
    interface: Optional[str]
    rssi_dbm: int           # 0 means not associated (CoreWLAN semantics)
    noise_dbm: int
    channel: Optional[int]
    band: Optional[str]
    phy_mode: str
    tx_rate_mbps: float
    ssid: Optional[str]
    read_ms: float

    @property
    def associated(self) -> bool:
        return self.rssi_dbm != 0


def parse_line(line: str) -> RssiSample:
    """Parse one JSON line emitted by mac_wifi_reader. Raises ValueError on bad input."""
    try:
        o = json.loads(line)
    except json.JSONDecodeError as e:
        raise ValueError(f"not JSON: {line[:80]!r}") from e
    try:
        return RssiSample(
            timestamp=o["timestamp"], t_mono=float(o["t_mono"]), seq=int(o["seq"]),
            interface=o.get("interface"), rssi_dbm=int(o["rssi_dbm"]),
            noise_dbm=int(o["noise_dbm"]), channel=o.get("channel"), band=o.get("band"),
            phy_mode=o.get("phy_mode", "unknown"), tx_rate_mbps=float(o.get("tx_rate_mbps", 0)),
            ssid=o.get("ssid"), read_ms=float(o.get("read_ms", 0)),
        )
    except KeyError as e:
        raise ValueError(f"missing field {e} in {line[:80]!r}") from e


class SensingBackend(ABC):
    name: str

    @abstractmethod
    def stream(self, hz: float, count: int = -1) -> Iterator[RssiSample]: ...

    def close(self) -> None: ...


class MacRSSIBackend(SensingBackend):
    """Streams real CoreWLAN link RSSI from the Swift helper subprocess."""
    name = "mac_rssi"

    def __init__(self, helper: Path = HELPER):
        if not helper.exists():
            raise FileNotFoundError(
                f"{helper} missing. Build: swiftc -O helper/mac_wifi_reader.swift -o bin/mac_wifi_reader")
        self.helper = helper
        self._proc: Optional[subprocess.Popen] = None

    def stream(self, hz: float, count: int = -1) -> Iterator[RssiSample]:
        self._proc = subprocess.Popen(
            [str(self.helper), "--hz", str(hz), "--count", str(count)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        try:
            for line in self._proc.stdout:
                if line.strip():
                    yield parse_line(line)
            rc = self._proc.wait()
            if rc != 0:
                raise RuntimeError(f"helper exit {rc}: {self._proc.stderr.read().strip()}")
        finally:
            self.close()

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            self._proc.wait(timeout=2)
