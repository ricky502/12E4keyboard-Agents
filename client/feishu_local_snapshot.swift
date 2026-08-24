import AppKit
import ApplicationServices

// Read-only accessibility snapshot of the locally logged-in Feishu client.
// It does not open a network connection, click, type, or send a message.
let bundleID = "com.bytedance.macos.feishu"
guard AXIsProcessTrusted() else {
    let data = try JSONSerialization.data(withJSONObject: ["ok": false,
        "err": "本机飞书采集器尚未获得 macOS 辅助功能权限"], options: [])
    FileHandle.standardOutput.write(data); exit(3)
}
guard let app = NSRunningApplication.runningApplications(withBundleIdentifier: bundleID).first else {
    fputs("Feishu is not running\n", stderr); exit(2)
}

let root = AXUIElementCreateApplication(app.processIdentifier)
var values: [String] = []
func attribute(_ element: AXUIElement, _ name: String) -> AnyObject? {
    var value: CFTypeRef?
    return AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success ? value : nil
}
func walk(_ element: AXUIElement, _ depth: Int = 0) {
    guard depth < 28 && values.count < 2400 else { return }
    for name in [kAXTitleAttribute, kAXDescriptionAttribute, kAXValueAttribute] {
        if let value = attribute(element, name) as? String {
            let trimmed = value.trimmingCharacters(in: CharacterSet.whitespacesAndNewlines)
            if !trimmed.isEmpty && !values.contains(trimmed) { values.append(trimmed) }
        }
    }
    if let children = attribute(element, kAXChildrenAttribute) as? [AXUIElement] {
        for child in children { walk(child, depth + 1) }
    }
}
walk(root)
let output: [String: Any] = ["ok": true, "pid": app.processIdentifier,
                              "text": values.joined(separator: "\n")]
let data = try JSONSerialization.data(withJSONObject: output, options: [])
FileHandle.standardOutput.write(data)
