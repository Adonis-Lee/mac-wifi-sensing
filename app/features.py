"""Window features for RSSI-only sensing (used by the ML baseline and reports).

Adapted ideas from RuView: v1 feature_extractor (skew/kurtosis/IQR, dominant frequency,
CUSUM change points) and v2 predictive_gate (EMA prediction residual). Differences:
- band edges are clipped to the measured Nyquist (v1 used 0.5-3.0 Hz regardless of fs)
- sample rate always comes from timestamps, never a default
"""
from __future__ import annotations

import numpy as np
from scipy import stats
from scipy.signal import welch

MOTION_BAND = (0.3, 2.0)


def cusum_change_points(x: np.ndarray, k_sigma: float = 0.5, h_sigma: float = 4.0,
                        sigma: float | None = None) -> list[int]:
    """Two-sided CUSUM on mean shifts. sigma defaults to the window std (floored at 0.5 dB,
    the RSSI quantization scale) so a flat window does not explode."""
    if len(x) < 4:
        return []
    sigma = max(sigma if sigma is not None else float(np.std(x, ddof=1)), 0.5)
    k, h = k_sigma * sigma, h_sigma * sigma
    ref = x[0]
    pos = neg = 0.0
    cps = []
    for i, v in enumerate(x):
        pos = max(0.0, pos + v - ref - k)
        neg = max(0.0, neg + ref - v - k)
        if pos > h or neg > h:
            cps.append(i)
            ref, pos, neg = v, 0.0, 0.0
    return cps


def ema_residual(x: np.ndarray, alpha: float = 0.3) -> float:
    """Mean |x - EMA prediction| (RuView v2 predictive gate idea, in dB instead of amplitude)."""
    if len(x) < 2:
        return 0.0
    pred, res = x[0], []
    for v in x[1:]:
        res.append(abs(v - pred))
        pred = alpha * v + (1 - alpha) * pred
    return float(np.mean(res))


def extract(x: np.ndarray, fs: float, baseline: float | None = None) -> dict:
    x = np.asarray(x, float)
    std = float(x.std(ddof=1)) if len(x) > 1 else 0.0
    q75, q25 = np.percentile(x, [75, 25])
    f = {
        "mean": float(x.mean()), "std": std, "var": std ** 2, "range": float(np.ptp(x)),
        "median": float(np.median(x)), "mad": float(np.median(np.abs(x - np.median(x)))),
        "iqr": float(q75 - q25),
        "skew": float(stats.skew(x, bias=False)) if std > 1e-9 and len(x) > 2 else 0.0,
        "kurtosis": float(stats.kurtosis(x, bias=False)) if std > 1e-9 and len(x) > 3 else 0.0,
        "deriv_energy": float(np.mean(np.diff(x) ** 2)) if len(x) > 1 else 0.0,
        "ema_residual": ema_residual(x),
        "n_change_points": len(cusum_change_points(x)),
    }
    if baseline is not None:
        f["shift"] = float(abs(x.mean() - baseline))
    nyq = fs / 2
    if len(x) >= 8:
        fr, p = welch(x - x.mean(), fs=fs, nperseg=len(x))
        lo, hi = MOTION_BAND[0], min(MOTION_BAND[1], nyq * 0.95)
        band = (fr >= lo) & (fr <= hi)
        f["motion_band_power"] = float(np.trapezoid(p[band], fr[band])) if band.sum() > 1 else 0.0
        f["total_power"] = float(np.trapezoid(p[1:], fr[1:])) if len(fr) > 2 else 0.0
        f["dominant_freq_hz"] = float(fr[1:][np.argmax(p[1:])]) if len(fr) > 1 else 0.0
    else:
        f.update(motion_band_power=0.0, total_power=0.0, dominant_freq_hz=0.0)
    return f
