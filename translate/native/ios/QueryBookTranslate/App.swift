import SwiftUI
import WebKit

/// QueryBook Translate — iPhone and iPad shell.
/// The UI and deterministic engine are the bundled web app (www/), served from a
/// local scheme so everything works with no network. NativeBridge fills the
/// speech roles with Apple's on-device recognizer and synthesizer.
@main
struct QueryBookTranslateApp: App {
    var body: some Scene {
        WindowGroup {
            WebContainer()
                .ignoresSafeArea()
        }
    }
}

struct WebContainer: UIViewRepresentable {
    func makeCoordinator() -> NativeBridge { NativeBridge() }

    func makeUIView(context: Context) -> WKWebView {
        context.coordinator.makeWebView()
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}
}
