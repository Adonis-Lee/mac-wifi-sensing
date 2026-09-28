import numpy as np
from app.features import cusum_change_points, ema_residual, extract


def test_cusum_finds_step_not_flat():
    assert cusum_change_points(np.full(50, -70.0)) == []
    step = np.r_[np.full(25, -70.0), np.full(25, -76.0)]
    cps = cusum_change_points(step)
    assert len(cps) == 1 and 25 <= cps[0] <= 28


def test_ema_residual_zero_when_constant():
    assert ema_residual(np.full(10, -70.0)) == 0


def test_band_clipped_to_nyquist_and_keys():
    x = -70 + np.sin(2 * np.pi * 1.0 * np.arange(50) / 5)
    f = extract(x, fs=5, baseline=-70)
    assert abs(f["dominant_freq_hz"] - 1.0) < 0.15
    assert f["motion_band_power"] > 0 and f["shift"] < 0.2
