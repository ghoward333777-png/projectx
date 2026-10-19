// iPhone (Face ID camera) → QueryBook: ARKit face blendshapes as 'face' events, 10 per second.
//
// Add this file to a SwiftUI/UIKit app with an ARSCNView or ARSession, set QB_URL and QB_DEVICE_KEY, and start it:
//     let sender = FaceSender(url: "http://192.168.1.20:9101", key: "qbd_...")
//     sender.start()
// Needs NSCameraUsageDescription in Info.plist and a device with a TrueDepth camera. The device needs 'people' consent
// in QueryBook. Only the 52 numbers per frame leave the phone — never the camera picture.
import ARKit
import Foundation

final class FaceSender: NSObject, ARSessionDelegate {
    private let session = ARSession()
    private let url: URL
    private let key: String
    private var buffer: [[String: Any]] = []
    private var lastSample = Date.distantPast
    private var lastSend = Date()

    init(url: String, key: String) {
        self.url = URL(string: url + "/api/devices/ingest")!
        self.key = key
        super.init()
        session.delegate = self
    }

    func start() {
        guard ARFaceTrackingConfiguration.isSupported else { print("No TrueDepth camera"); return }
        session.run(ARFaceTrackingConfiguration())
    }

    func stop() { session.pause(); send() }

    func session(_ session: ARSession, didUpdate anchors: [ARAnchor]) {
        guard let face = anchors.compactMap({ $0 as? ARFaceAnchor }).first, Date().timeIntervalSince(lastSample) >= 0.1 else { return }
        lastSample = Date()
        var shapes: [String: Double] = [:]
        for (loc, value) in face.blendShapes { shapes[loc.rawValue] = Double(truncating: value) }   // rawValue = ARKit name, e.g. "jawOpen"
        buffer.append(["kind": "face", "t": Date().timeIntervalSince1970, "data": ["blendshapes": shapes]])
        if Date().timeIntervalSince(lastSend) >= 2 { send() }
    }

    private func send() {
        guard !buffer.isEmpty else { return }
        let events = buffer; buffer = []; lastSend = Date()
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("Bearer " + key, forHTTPHeaderField: "Authorization")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["events": events])
        URLSession.shared.dataTask(with: req) { _, resp, err in
            if err != nil || (resp as? HTTPURLResponse)?.statusCode != 200 { print("QueryBook send failed", err ?? "") }
        }.resume()
    }
}
