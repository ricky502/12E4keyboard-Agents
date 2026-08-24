import AppKit
import ScreenCaptureKit
import Vision

// Captures only the on-screen Feishu window and performs OCR locally. This
// requires macOS Screen Recording permission when run; it has no network code.
do {
    let content = try await SCShareableContent.current
    guard let window = content.windows.first(where: {
        $0.owningApplication?.bundleIdentifier == "com.bytedance.macos.feishu" && $0.isOnScreen
    }) else { throw NSError(domain: "Agentpad", code: 3,
                              userInfo: [NSLocalizedDescriptionKey: "无法找到本机飞书窗口"])
    }
    let filter = SCContentFilter(desktopIndependentWindow: window)
    let image: CGImage = try await withCheckedThrowingContinuation { continuation in
        SCScreenshotManager.captureImage(contentFilter: filter, configuration: SCStreamConfiguration()) {
            image, error in
            if let image { continuation.resume(returning: image) }
            else { continuation.resume(throwing: error ?? NSError(domain: "Agentpad", code: 4)) }
        }
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = false
    let handler = VNImageRequestHandler(cgImage: image, options: [:])
    try handler.perform([request])
    let text = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
    let data = try JSONSerialization.data(withJSONObject: ["ok": true, "text": text])
    FileHandle.standardOutput.write(data)
} catch {
    let data = try JSONSerialization.data(withJSONObject: ["ok": false, "err": error.localizedDescription])
    FileHandle.standardOutput.write(data); exit(4)
}
