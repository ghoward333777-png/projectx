import AVFoundation
import Foundation
import Speech
import UniformTypeIdentifiers
import WebKit

/// Serves the bundled web app and bridges speech.
/// Protocol: JS → native: postMessage(JSON string {id, cmd, ...});
/// native → JS: window.qbtNative.emit({id?, type, ...}).
final class NativeBridge: NSObject, WKScriptMessageHandler, WKURLSchemeHandler, AVSpeechSynthesizerDelegate {
    private static let scheme = "qbt"
    private weak var webView: WKWebView?
    private let synthesizer = AVSpeechSynthesizer()
    private var utterances: [ObjectIdentifier: Int] = [:]
    private let audioEngine = AVAudioEngine()
    private var recognitionTask: SFSpeechRecognitionTask?
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var listenId = 0
    private var silenceTimer: Timer?
    private var lastText = ""
    private var lastConfidence: Double?

    func makeWebView() -> WKWebView {
        let config = WKWebViewConfiguration()
        config.setURLSchemeHandler(self, forURLScheme: Self.scheme)
        config.userContentController.add(self, name: "qbt")
        config.allowsInlineMediaPlayback = true
        let web = WKWebView(frame: .zero, configuration: config)
        web.scrollView.contentInsetAdjustmentBehavior = .never
        if #available(iOS 16.4, *) { web.isInspectable = true }
        synthesizer.delegate = self
        webView = web
        web.load(URLRequest(url: URL(string: "\(Self.scheme)://app/index.html")!))
        return web
    }

    // MARK: - Local scheme: serve www/ from the app bundle

    func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
        guard let url = task.request.url, let root = Bundle.main.url(forResource: "www", withExtension: nil) else {
            task.didFailWithError(URLError(.fileDoesNotExist)); return
        }
        var path = url.path.isEmpty || url.path == "/" ? "/index.html" : url.path
        path = path.removingPercentEncoding ?? path
        let file = root.appendingPathComponent(String(path.dropFirst())).standardizedFileURL
        guard file.path.hasPrefix(root.standardizedFileURL.path), let data = try? Data(contentsOf: file) else {
            let r = HTTPURLResponse(url: url, statusCode: 404, httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "text/plain"])!
            task.didReceive(r); task.didReceive(Data()); task.didFinish(); return
        }
        let mime = UTType(filenameExtension: file.pathExtension)?.preferredMIMEType
            ?? (file.pathExtension == "webmanifest" ? "application/manifest+json" : "application/octet-stream")
        let headers = ["Content-Type": file.pathExtension == "js" ? "text/javascript" : mime, "Cache-Control": "no-cache"]
        task.didReceive(HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: headers)!)
        task.didReceive(data)
        task.didFinish()
    }

    func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {}

    // MARK: - Messages from the page

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? String, let data = body.data(using: .utf8),
              let msg = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return }
        let id = msg["id"] as? Int ?? 0
        switch msg["cmd"] as? String ?? "" {
        case "hello": sendVoices()
        case "listen": listen(id: id, tag: msg["tag"] as? String ?? "en-US")
        case "stopListening": finishListening()
        case "speak": speak(id: id, text: msg["text"] as? String ?? "", voice: msg["voice"] as? String ?? "", rate: msg["rate"] as? Double ?? 1)
        case "asrOnDevice":
            let tag = msg["tag"] as? String ?? "en-US"
            emit(["id": id, "onDevice": SFSpeechRecognizer(locale: Locale(identifier: tag))?.supportsOnDeviceRecognition ?? false])
        default: break
        }
    }

    // MARK: - Speech in (untrusted input: shown for confirmation in the UI)

    private func listen(id: Int, tag: String) {
        finishListening()
        listenId = id
        SFSpeechRecognizer.requestAuthorization { status in
            DispatchQueue.main.async {
                guard status == .authorized else {
                    self.stream(id, "error", ["code": "not-allowed", "message": "Speech recognition permission was denied."]); self.stream(id, "end"); return
                }
                AVAudioSession.sharedInstance().requestRecordPermission { granted in
                    DispatchQueue.main.async {
                        guard granted else {
                            self.stream(id, "error", ["code": "not-allowed", "message": "Microphone permission was denied."]); self.stream(id, "end"); return
                        }
                        self.startRecognition(id: id, tag: tag)
                    }
                }
            }
        }
    }

    private func startRecognition(id: Int, tag: String) {
        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: tag)), recognizer.isAvailable else {
            stream(id, "error", ["code": "language-not-supported", "message": "This device cannot recognize \(tag) speech yet — type instead."]); stream(id, "end"); return
        }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .measurement, options: [.defaultToSpeaker, .allowBluetooth])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            stream(id, "error", ["code": "audio-capture", "message": "Could not start the microphone."]); stream(id, "end"); return
        }
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition { request.requiresOnDeviceRecognition = true }
        recognitionRequest = request
        lastText = ""
        lastConfidence = nil
        let input = audioEngine.inputNode
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: input.outputFormat(forBus: 0)) { buffer, _ in request.append(buffer) }
        audioEngine.prepare()
        do { try audioEngine.start() } catch {
            stream(id, "error", ["code": "audio-capture", "message": "No microphone available."]); stream(id, "end"); return
        }
        armSilenceTimer(seconds: 6)
        recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self = self else { return }
            DispatchQueue.main.async {
                if let result = result {
                    self.lastText = result.bestTranscription.formattedString
                    let segs = result.bestTranscription.segments
                    if !segs.isEmpty { self.lastConfidence = Double(segs.map(\.confidence).reduce(0, +)) / Double(segs.count) }
                    self.stream(id, "partial", ["text": self.lastText])
                    self.armSilenceTimer(seconds: 1.4)
                    if result.isFinal { self.complete() }
                } else if error != nil {
                    if self.lastText.isEmpty { self.stream(id, "error", ["code": "no-speech", "message": "No speech heard."]) }
                    self.complete()
                }
            }
        }
    }

    private func armSilenceTimer(seconds: TimeInterval) {
        silenceTimer?.invalidate()
        silenceTimer = Timer.scheduledTimer(withTimeInterval: seconds, repeats: false) { [weak self] _ in self?.finishListening() }
    }

    /// Stop capturing; the recognizer then delivers its final result.
    private func finishListening() {
        silenceTimer?.invalidate()
        guard audioEngine.isRunning else { return }
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
    }

    private func complete() {
        guard recognitionTask != nil else { return }
        finishListening()
        recognitionTask = nil
        recognitionRequest = nil
        var final: [String: Any] = ["text": lastText]
        if let c = lastConfidence, c > 0 { final["confidence"] = c }
        if !lastText.isEmpty { stream(listenId, "final", final) }
        stream(listenId, "end")
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
    }

    // MARK: - Speech out (never a substitute voice)

    private func sendVoices() {
        let voices = AVSpeechSynthesisVoice.speechVoices().map { v -> [String: Any] in
            ["id": v.identifier, "name": v.name, "lang": v.language, "onDevice": true]
        }
        emit(["type": "voices", "voices": voices])
    }

    private func speak(id: Int, text: String, voice: String, rate: Double) {
        guard let v = AVSpeechSynthesisVoice(identifier: voice) else {
            emit(["id": id, "ok": false, "detail": "That voice is not installed on this device."]); return
        }
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
        let u = AVSpeechUtterance(string: text)
        u.voice = v
        u.rate = Float(min(max(Double(AVSpeechUtteranceDefaultSpeechRate) * rate, Double(AVSpeechUtteranceMinimumSpeechRate)), Double(AVSpeechUtteranceMaximumSpeechRate)))
        utterances[ObjectIdentifier(u)] = id
        synthesizer.stopSpeaking(at: .immediate)
        synthesizer.speak(u)
    }

    func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish u: AVSpeechUtterance) {
        if let id = utterances.removeValue(forKey: ObjectIdentifier(u)) { emit(["id": id, "ok": true, "detail": u.voice?.name ?? "voice"]) }
    }

    func speechSynthesizer(_ s: AVSpeechSynthesizer, didCancel u: AVSpeechUtterance) {
        if let id = utterances.removeValue(forKey: ObjectIdentifier(u)) { emit(["id": id, "ok": true, "detail": "stopped"]) }
    }

    // MARK: - To the page

    private func stream(_ id: Int, _ type: String, _ extra: [String: Any] = [:]) {
        var o = extra
        o["id"] = id
        o["type"] = type
        emit(o)
    }

    private func emit(_ object: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: object), let json = String(data: data, encoding: .utf8) else { return }
        DispatchQueue.main.async { self.webView?.evaluateJavaScript("window.qbtNative && window.qbtNative.emit(\(json))") }
    }
}
