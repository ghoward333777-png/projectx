package com.querybook.translate;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.speech.tts.Voice;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.webkit.WebViewAssetLoader;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;

/**
 * QueryBook Translate — Android shell.
 *
 * The UI and the deterministic translation engine are the bundled web app
 * (assets/www), served from a secure local origin so it works with no network.
 * This activity fills the two speech roles with the device's own engines:
 * SpeechRecognizer (on-device when available) and TextToSpeech. ASR text is
 * untrusted input; TTS never substitutes a voice for a language it lacks.
 */
public class MainActivity extends Activity {
    private static final String ORIGIN = "https://appassets.androidplatform.net";
    private static final int REQ_MIC = 7;

    private WebView web;
    private WebViewAssetLoader assets;
    private SpeechRecognizer recognizer;
    private TextToSpeech tts;
    private boolean ttsReady = false;
    private JSONObject pendingListen;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        assets = new WebViewAssetLoader.Builder()
                .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setMediaPlaybackRequiresUserGesture(false);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                return assets.shouldInterceptRequest(request.getUrl());
            }
        });
        web.addJavascriptInterface(new Bridge(), "QBTAndroid");
        setContentView(web);
        web.loadUrl(ORIGIN + "/assets/www/index.html");

        tts = new TextToSpeech(this, status -> {
            ttsReady = status == TextToSpeech.SUCCESS;
            sendVoices();
        });
        tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
            @Override public void onStart(String id) { }
            @Override public void onDone(String id) { reply(Integer.parseInt(id), true, "spoken"); }
            @Override public void onError(String id) { reply(Integer.parseInt(id), false, "Speech failed"); }
        });
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (recognizer != null) recognizer.destroy();
        if (tts != null) tts.shutdown();
        web.destroy();
        super.onDestroy();
    }

    // ------------------------------------------------------------------ bridge

    private class Bridge {
        @JavascriptInterface
        public void postMessage(String json) {
            runOnUiThread(() -> {
                try {
                    handle(new JSONObject(json));
                } catch (JSONException e) {
                    // Malformed message from the page: ignore.
                }
            });
        }
    }

    private void handle(JSONObject msg) throws JSONException {
        String cmd = msg.optString("cmd");
        int id = msg.optInt("id", 0);
        switch (cmd) {
            case "hello":
                sendVoices();
                break;
            case "listen":
                if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                    pendingListen = msg;
                    requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_MIC);
                } else {
                    listen(id, msg.optString("tag", "en-US"));
                }
                break;
            case "stopListening":
                if (recognizer != null) recognizer.stopListening();
                break;
            case "speak":
                speak(id, msg.optString("text"), msg.optString("voice"), msg.optDouble("rate", 1.0));
                break;
            case "asrOnDevice": {
                JSONObject out = new JSONObject().put("id", id);
                if (Build.VERSION.SDK_INT >= 31) out.put("onDevice", SpeechRecognizer.isOnDeviceRecognitionAvailable(this));
                emit(out);
                break;
            }
            default:
                break;
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode != REQ_MIC || pendingListen == null) return;
        JSONObject msg = pendingListen;
        pendingListen = null;
        int id = msg.optInt("id", 0);
        if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) {
            listen(id, msg.optString("tag", "en-US"));
        } else {
            streamEvent(id, "error", null, "not-allowed", "Microphone permission was denied.", -1);
            streamEvent(id, "end", null, null, null, -1);
        }
    }

    // ------------------------------------------------------------------ speech in

    private void listen(int id, String tag) {
        if (recognizer != null) recognizer.destroy();
        if (Build.VERSION.SDK_INT >= 31 && SpeechRecognizer.isOnDeviceRecognitionAvailable(this)) {
            recognizer = SpeechRecognizer.createOnDeviceSpeechRecognizer(this);
        } else if (SpeechRecognizer.isRecognitionAvailable(this)) {
            recognizer = SpeechRecognizer.createSpeechRecognizer(this);
        } else {
            streamEvent(id, "error", null, "unsupported", "No speech recognizer on this device — type instead.", -1);
            streamEvent(id, "end", null, null, null, -1);
            return;
        }
        Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, tag);
        intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
        intent.putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true);
        intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
        recognizer.setRecognitionListener(new RecognitionListener() {
            boolean ended = false;

            private void end() {
                if (!ended) { ended = true; streamEvent(id, "end", null, null, null, -1); }
            }

            @Override public void onReadyForSpeech(Bundle params) { }
            @Override public void onBeginningOfSpeech() { }
            @Override public void onRmsChanged(float rmsdB) { }
            @Override public void onBufferReceived(byte[] buffer) { }
            @Override public void onEndOfSpeech() { }
            @Override public void onEvent(int eventType, Bundle params) { }

            @Override
            public void onPartialResults(Bundle partial) {
                ArrayList<String> r = partial.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                if (r != null && !r.isEmpty()) streamEvent(id, "partial", r.get(0), null, null, -1);
            }

            @Override
            public void onResults(Bundle results) {
                ArrayList<String> r = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                float[] conf = results.getFloatArray(SpeechRecognizer.CONFIDENCE_SCORES);
                if (r != null && !r.isEmpty()) {
                    streamEvent(id, "final", r.get(0), null, null, conf != null && conf.length > 0 && conf[0] >= 0 ? conf[0] : -1);
                }
                end();
            }

            @Override
            public void onError(int error) {
                String code;
                String message;
                switch (error) {
                    case SpeechRecognizer.ERROR_NETWORK:
                    case SpeechRecognizer.ERROR_NETWORK_TIMEOUT:
                        code = "network";
                        message = "This language needs the online recognizer on this device. Type instead, or download offline speech for it in system settings.";
                        break;
                    case SpeechRecognizer.ERROR_NO_MATCH:
                    case SpeechRecognizer.ERROR_SPEECH_TIMEOUT:
                        code = "no-speech";
                        message = "No speech heard.";
                        break;
                    case SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS:
                        code = "not-allowed";
                        message = "Microphone permission was denied.";
                        break;
                    case SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED:
                    case SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE:
                        code = "language-not-supported";
                        message = "This device cannot recognize " + tag + " speech yet — type instead.";
                        break;
                    default:
                        code = "native";
                        message = "Recognition error " + error + ".";
                }
                streamEvent(id, "error", null, code, message, -1);
                end();
            }
        });
        recognizer.startListening(intent);
    }

    // ------------------------------------------------------------------ speech out

    private void sendVoices() {
        if (!ttsReady) return;
        try {
            JSONArray list = new JSONArray();
            if (tts.getVoices() != null) {
                for (Voice v : tts.getVoices()) {
                    if (v.getFeatures() != null && v.getFeatures().contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED)) continue;
                    list.put(new JSONObject()
                            .put("id", v.getName())
                            .put("name", v.getName())
                            .put("lang", v.getLocale().toLanguageTag())
                            .put("onDevice", !v.isNetworkConnectionRequired()));
                }
            }
            emit(new JSONObject().put("type", "voices").put("voices", list));
        } catch (JSONException ignored) {
            // Never thrown for well-formed values.
        }
    }

    private void speak(int id, String text, String voiceName, double rate) {
        if (!ttsReady) { reply(id, false, "The speech engine is still starting."); return; }
        Voice chosen = null;
        if (tts.getVoices() != null) {
            for (Voice v : tts.getVoices()) if (v.getName().equals(voiceName)) { chosen = v; break; }
        }
        if (chosen == null) { reply(id, false, "That voice is not installed on this device."); return; }
        tts.setVoice(chosen);
        tts.setSpeechRate((float) rate);
        tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, String.valueOf(id));
    }

    // ------------------------------------------------------------------ to JS

    private void reply(int id, boolean ok, String detail) {
        try {
            emit(new JSONObject().put("id", id).put("ok", ok).put("detail", detail));
        } catch (JSONException ignored) { }
    }

    private void streamEvent(int id, String type, String text, String code, String message, float confidence) {
        try {
            JSONObject o = new JSONObject().put("id", id).put("type", type);
            if (text != null) o.put("text", text);
            if (code != null) o.put("code", code);
            if (message != null) o.put("message", message);
            if (confidence >= 0) o.put("confidence", (double) confidence);
            emit(o);
        } catch (JSONException ignored) { }
    }

    private void emit(JSONObject o) {
        String js = "window.qbtNative && window.qbtNative.emit(" + JSONObject.quote(o.toString()) + ")";
        web.post(() -> web.evaluateJavascript(js, null));
    }
}
