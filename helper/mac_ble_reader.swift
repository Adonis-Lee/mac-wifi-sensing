// mac_ble_reader — nearby Bluetooth LE advertisers with RSSI (CoreBluetooth).
// Runs as an .app (MacBLE.app) so macOS attributes the Bluetooth permission to it.
// Usage: open -g -n MacBLE.app --args --out <snapshot.json>
// Writes a snapshot every 2 s: {"state": "...", "devices": [{"id","rssi_dbm","name","age_s"}]}
import CoreBluetooth
import Foundation

final class Scanner: NSObject, CBCentralManagerDelegate {
    var central: CBCentralManager!
    var seen: [UUID: (rssi: [Int], name: String?, last: Date)] = [:]
    var state = "unknown"
    override init() { super.init(); central = CBCentralManager(delegate: self, queue: .main) }

    func centralManagerDidUpdateState(_ c: CBCentralManager) {
        switch c.state {
        case .poweredOn: state = "on"
            c.scanForPeripherals(withServices: nil, options: [CBCentralManagerScanOptionAllowDuplicatesKey: true])
        case .poweredOff: state = "off"
        case .unauthorized: state = "unauthorized"
        case .unsupported: state = "unsupported"
        default: state = "unknown"
        }
    }

    func centralManager(_ c: CBCentralManager, didDiscover p: CBPeripheral,
                        advertisementData a: [String: Any], rssi: NSNumber) {
        let r = rssi.intValue
        guard r < 0 && r > -110 else { return }  // 127 = unavailable
        var e = seen[p.identifier] ?? (rssi: [], name: nil, last: Date())
        e.rssi = Array((e.rssi + [r]).suffix(5))
        e.name = p.name ?? (a[CBAdvertisementDataLocalNameKey] as? String) ?? e.name
        e.last = Date()
        seen[p.identifier] = e
    }

    func snapshot() -> [String: Any] {
        let now = Date()
        seen = seen.filter { now.timeIntervalSince($0.value.last) < 15 }
        let devs: [[String: Any]] = seen.map { id, e in
            let s = e.rssi.sorted()
            return ["id": String(id.uuidString.prefix(8)), "rssi_dbm": s[s.count / 2],
                    "name": e.name ?? NSNull(), "age_s": now.timeIntervalSince(e.last)]
        }
        return ["state": state, "timestamp": ISO8601DateFormatter().string(from: now), "devices": devs]
    }
}

var out: String?
var it = CommandLine.arguments.dropFirst().makeIterator()
while let a = it.next() { if a == "--out" { out = it.next() } }
guard let outPath = out else { FileHandle.standardError.write("need --out\n".data(using: .utf8)!); exit(2) }

let scanner = Scanner()
Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { _ in
    if let d = try? JSONSerialization.data(withJSONObject: scanner.snapshot()) {
        let tmp = outPath + ".tmp"
        FileManager.default.createFile(atPath: tmp, contents: d)
        _ = try? FileManager.default.replaceItemAt(URL(fileURLWithPath: outPath), withItemAt: URL(fileURLWithPath: tmp))
    }
    // exit if the parent (python) stopped refreshing the heartbeat file
    let hb = outPath + ".alive"
    if let attrs = try? FileManager.default.attributesOfItem(atPath: hb),
       let m = attrs[.modificationDate] as? Date, Date().timeIntervalSince(m) > 20 { exit(0) }
}
RunLoop.main.run()
