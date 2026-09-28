#!/bin/sh
# Builds the CoreWLAN reader and the Bluetooth reader app bundle into bin/.
set -e
cd "$(dirname "$0")/.."
mkdir -p bin
swiftc -O helper/mac_wifi_reader.swift -o bin/mac_wifi_reader
APP=bin/MacBLE.app
rm -rf "$APP" && mkdir -p "$APP/Contents/MacOS"
cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>local.macwifisensing.ble</string>
<key>CFBundleName</key><string>MacBLE</string>
<key>CFBundleExecutable</key><string>mac_ble_reader</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSUIElement</key><true/>
<key>NSBluetoothAlwaysUsageDescription</key><string>Measures signal strength (RSSI) of nearby Bluetooth devices for the RF view.</string>
</dict></plist>
PL
swiftc -O helper/mac_ble_reader.swift -o "$APP/Contents/MacOS/mac_ble_reader"
codesign -s - --force "$APP" >/dev/null
echo "built bin/mac_wifi_reader and $APP"
