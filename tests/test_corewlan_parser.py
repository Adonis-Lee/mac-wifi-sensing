import pytest
from app.backend import parse_line

LINE = ('{"associated":true,"band":"5GHz","bssid":null,"channel":36,"interface":"en0",'
        '"noise_dbm":-94,"phy_mode":"802.11ax","power_on":true,"read_ms":2.9,"rssi_dbm":-62,'
        '"seq":0,"ssid":null,"t_mono":226014.46,"timestamp":"2026-09-28T11:47:08.121Z","tx_rate_mbps":720}')


def test_parses_helper_line():
    s = parse_line(LINE)
    assert (s.rssi_dbm, s.noise_dbm, s.channel, s.ssid) == (-62, -94, 36, None)
    assert s.associated


def test_zero_rssi_means_not_associated():
    assert not parse_line(LINE.replace('"rssi_dbm":-62', '"rssi_dbm":0')).associated


@pytest.mark.parametrize("bad", ["not json", '{"seq":1}'])
def test_rejects_bad_lines(bad):
    with pytest.raises(ValueError):
        parse_line(bad)
