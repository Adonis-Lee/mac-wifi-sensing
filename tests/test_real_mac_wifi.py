"""Integration: real CoreWLAN hardware. SKIPPED when helper missing or Wi-Fi not associated."""
import pytest
from app.backend import HELPER, MacRSSIBackend

pytestmark = pytest.mark.skipif(not HELPER.exists(), reason="helper not built")


def test_real_samples():
    samples = list(MacRSSIBackend().stream(hz=5, count=10))
    if not samples[0].associated:
        pytest.skip("Wi-Fi not associated (rssiValue()==0)")
    assert len(samples) == 10
    assert all(-100 <= s.rssi_dbm < 0 for s in samples)
    rate = 9 / (samples[-1].t_mono - samples[0].t_mono)
    assert 4 < rate < 6
