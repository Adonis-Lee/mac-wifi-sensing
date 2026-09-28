# mac-wifi-sensing

RSSI-only Wi-Fi sensing using the MacBook's built-in Wi-Fi via CoreWLAN. Not CSI.

```
swiftc -O helper/mac_wifi_reader.swift -o bin/mac_wifi_reader
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m app.diagnose                       # M0 check
.venv/bin/python -m app.log --hz 5 --duration 60 --room home --label EMPTY
.venv/bin/python -m app.quality data/raw/<file>.csv
.venv/bin/python -m app.live --hz 5
.venv/bin/python -m pytest -q
```

Raw recordings in `data/raw/` (CSV + `.meta.json`) are never modified; derived data goes to `data/processed/`.
SSID/BSSID are null unless Location Services is granted; they are not needed for sensing.
