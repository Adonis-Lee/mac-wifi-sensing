// mac_wifi_reader — CoreWLAN RSSI reader. Emits one JSON object per line.
// Usage: mac_wifi_reader [--once] [--hz N] [--count N]
// Only fields returned by CoreWLAN are emitted; unavailable fields are null.
import CoreWLAN
import Foundation

func phyName(_ m: CWPHYMode) -> String {
    switch m {
    case .mode11a: return "802.11a"
    case .mode11b: return "802.11b"
    case .mode11g: return "802.11g"
    case .mode11n: return "802.11n"
    case .mode11ac: return "802.11ac"
    case .mode11ax: return "802.11ax"
    case .mode11be: return "802.11be"
    case .modeNone: return "none"
    @unknown default: return "unknown(\(m.rawValue))"
    }
}

func bandName(_ b: CWChannelBand) -> String {
    switch b {
    case .band2GHz: return "2.4GHz"
    case .band5GHz: return "5GHz"
    case .band6GHz: return "6GHz"
    default: return "unknown"
    }
}

var once = false, hz = 1.0, count = -1
var args = CommandLine.arguments.dropFirst().makeIterator()
while let a = args.next() {
    switch a {
    case "--once": once = true
    case "--hz": hz = Double(args.next() ?? "1") ?? 1
    case "--count": count = Int(args.next() ?? "-1") ?? -1
    default: break
    }
}
if once { count = 1 }

guard let iface = CWWiFiClient.shared().interface() else {
    FileHandle.standardError.write("ERROR: no Wi-Fi interface from CWWiFiClient\n".data(using: .utf8)!)
    exit(2)
}

let iso = ISO8601DateFormatter()
iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

// --scan-once: one JSON line listing visible networks (results may be cached by macOS;
// ssid/bssid are nil without Location Services, so networks are anonymous).
if CommandLine.arguments.contains("--scan-once") {
    do {
        let nets = try iface.scanForNetworks(withSSID: nil)
        let list: [[String: Any]] = nets.map { n in [
            "rssi_dbm": n.rssiValue, "noise_dbm": n.noiseMeasurement,
            "channel": n.wlanChannel.map { $0.channelNumber } ?? NSNull(),
            "band": n.wlanChannel.map { bandName($0.channelBand) } ?? NSNull(),
            "ssid": n.ssid ?? NSNull(),
        ] }
        let o: [String: Any] = ["timestamp": iso.string(from: Date()), "networks": list]
        print(String(data: try JSONSerialization.data(withJSONObject: o, options: [.sortedKeys]), encoding: .utf8)!)
        exit(0)
    } catch {
        FileHandle.standardError.write("ERROR: scan failed: \(error)\n".data(using: .utf8)!)
        exit(3)
    }
}
let period = 1.0 / max(hz, 0.01)
var n = 0
var next = Date()
setvbuf(stdout, nil, _IOLBF, 0)

while count < 0 || n < count {
    let t0 = Date()
    let rssi = iface.rssiValue()          // 0 when not associated
    let noise = iface.noiseMeasurement()  // 0 when not associated
    let ch = iface.wlanChannel()
    let readMs = Date().timeIntervalSince(t0) * 1000

    var o: [String: Any] = [
        "timestamp": iso.string(from: t0),
        "t_mono": ProcessInfo.processInfo.systemUptime,
        "interface": iface.interfaceName ?? NSNull(),
        "power_on": iface.powerOn(),
        "rssi_dbm": rssi,
        "noise_dbm": noise,
        "channel": ch.map { $0.channelNumber } ?? NSNull(),
        "band": ch.map { bandName($0.channelBand) } ?? NSNull(),
        "phy_mode": phyName(iface.activePHYMode()),
        "tx_rate_mbps": iface.transmitRate(),
        // ssid/bssid return nil without Location Services authorization
        "ssid": iface.ssid() ?? NSNull(),
        "bssid": iface.bssid() ?? NSNull(),
        "read_ms": readMs,
        "seq": n,
    ]
    o["associated"] = rssi != 0
    let data = try! JSONSerialization.data(withJSONObject: o, options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
    n += 1
    next = next.addingTimeInterval(period)
    let wait = next.timeIntervalSinceNow
    if wait > 0 { Thread.sleep(forTimeInterval: wait) } else { next = Date() }
}
