# RuView review (main @ 5ef001b, 2026-09-27) — what we took, what we did not

## macOS path in RuView
- Helper: `archive/v1/src/sensing/mac_wifi.swift` (connected-link RSSI; `--scan-once` added in PR #1845).
- Rust: `v2/crates/wifi-densepose-wifiscan/src/adapter/macos_scanner.rs` spawns `mac_wifi --scan-once` per tick.
- Server: `v2/crates/wifi-densepose-sensing-server/src/main.rs` (`--source auto|wifi|esp32|simulate`).
- Open PRs #191, #192, #812 propose other macOS bridges (multi-BSSID); not merged.

## Findings that matter for us
1. v2 multi-BSSID pipeline (`WindowsWifiPipeline`) requires `min_bssids = 3`; macOS delivers 1
   observation, so the 8-stage pipeline (predictive gate, attention, correlator, breathing, quality
   gate) returns an empty/deny result every tick on macOS. Classification then runs on a
   1-"subcarrier" pseudo-CSI frame.
2. The macOS task builds its frame with `freq_mhz: 2437` and `noise_floor: -90` constants, not the
   measured channel/noise.
3. `--source auto` can serve simulated data when no real source is up (main.rs ~4569). Use `wifi`.
4. v1 Python: hard-coded thresholds (0.5 variance, 0.1 motion energy); sample-rate fallback 10 Hz;
   motion band 0.5-3.0 Hz exceeds Nyquist at <6 Hz sampling.
5. Research R8 ("RSSI keeps 95% of CSI accuracy") uses RSSI *simulated* by averaging CSI
   subcarriers, 2-class, 59% accuracy vs 50% chance. Not evidence about real RSSI hardware.
6. Docker images are Linux; CoreWLAN code is `cfg(target_os = "macos")` and absent in containers.

## Measured on this Mac (M2, macOS 26.6.2)
- Connected-link RSSI: 5 Hz sampling works; value changes ~every 0.4 s; 1 dB steps.
- `scanForNetworks`: 10 networks, SSID/BSSID all nil without Location Services, results cached,
  distinct results only ~0.25 Hz. Without AP identity, per-AP time series cannot be tracked
  reliably -> multi-AP mode NOT adopted.

## Adopted (app/features.py)
- skewness, kurtosis, IQR, dominant frequency, CUSUM change points (v1)
- EMA prediction residual (v2 predictive gate), in dB
- all band edges clipped to measured Nyquist; fs from timestamps only

## Not adopted
- Running RuView's Rust server: Rust toolchain not installed; for macOS it adds no signal
  beyond our helper (see findings 1-2). Can be revisited for side-by-side comparison.
- Breathing extraction: 1 dB / ~2.5 Hz effective RSSI is insufficient; would need CSI.
