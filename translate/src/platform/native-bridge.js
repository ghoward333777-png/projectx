// Native shell bridge. When the app runs inside the Android or iOS/iPadOS
// shell (native/android, native/ios), the shell exposes the device's own
// speech engines — Android SpeechRecognizer + TextToSpeech, Apple
// SFSpeechRecognizer (on-device) + AVSpeechSynthesizer — and this module
// registers them in the speech roles. In a browser it does nothing.
//
// Protocol: JS → native: post({id, cmd, ...}) as JSON. Native → JS:
// window.qbtNative.emit({id?, type, ...}).

import { registerAsr, registerTts } from './speech.js';

const pending = new Map();
const streams = new Map();
let seq = 0;
let voices = [];
let shell = null;

function post(msg) {
  const body = JSON.stringify(msg);
  if (window.QBTAndroid && window.QBTAndroid.postMessage) window.QBTAndroid.postMessage(body);
  else if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.qbt) window.webkit.messageHandlers.qbt.postMessage(body);
}

function request(cmd, args = {}, timeoutMs = 8000) {
  const id = ++seq;
  return new Promise((resolve) => {
    const timer = setTimeout(() => { pending.delete(id); resolve({ ok: false, detail: 'native shell did not answer' }); }, timeoutMs);
    pending.set(id, (v) => { clearTimeout(timer); resolve(v); });
    post({ id, cmd, ...args });
  });
}

export function detectShell() {
  if (typeof window === 'undefined') return null;
  if (window.QBTAndroid) return 'android';
  if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.qbt) return 'ios';
  return null;
}

export function installNativeBridge() {
  shell = detectShell();
  if (!shell) return null;
  window.qbtNative = {
    emit(ev) {
      if (typeof ev === 'string') ev = JSON.parse(ev);
      if (ev.type === 'voices') { voices = ev.voices || []; window.dispatchEvent(new Event('qbt-voices')); return; }
      if (ev.id && streams.has(ev.id)) {
        const s = streams.get(ev.id);
        if (ev.type === 'partial') s.onPartial && s.onPartial(ev.text);
        else if (ev.type === 'final') s.onFinal && s.onFinal({ text: ev.text, confidence: typeof ev.confidence === 'number' ? ev.confidence : null });
        else if (ev.type === 'error') s.onError && s.onError(ev.code || 'native', ev.message || 'Recognition error');
        else if (ev.type === 'end') { streams.delete(ev.id); s.onEnd && s.onEnd(); }
        return;
      }
      if (ev.id && pending.has(ev.id)) { pending.get(ev.id)(ev); pending.delete(ev.id); }
    },
  };

  registerAsr({
    name: shell === 'android' ? 'Android speech recognizer' : 'Apple speech recognizer',
    async onDevice(tag) {
      const r = await request('asrOnDevice', { tag });
      return typeof r.onDevice === 'boolean' ? r.onDevice : null;
    },
    start({ tag, onPartial, onFinal, onError, onEnd }) {
      const id = ++seq;
      streams.set(id, { onPartial, onFinal, onError, onEnd });
      post({ id, cmd: 'listen', tag, preferOnDevice: true });
      return () => post({ id, cmd: 'stopListening' });
    },
  });

  const norm = (t) => (t || '').replace('_', '-').toLowerCase();
  registerTts({
    voices: () => voices.map((v) => ({ name: v.name, lang: v.lang, onDevice: !!v.onDevice })),
    pickVoice(tag) {
      const want = norm(tag);
      const base = want.split('-')[0];
      const exact = voices.filter((v) => norm(v.lang) === want);
      const same = voices.filter((v) => norm(v.lang).split('-')[0] === base);
      const pick = [...exact.filter((v) => v.onDevice), ...same.filter((v) => v.onDevice), ...exact, ...same][0];
      return pick ? { voice: pick, onDevice: !!pick.onDevice, exact: norm(pick.lang) === want } : null;
    },
    async speak(text, tag, { rate = 1 } = {}) {
      const pick = this.pickVoice(tag);
      if (!pick) return { ok: false, detail: `No real ${tag} voice is installed on this device, so nothing is played. Add one in the system text-to-speech settings.` };
      const r = await request('speak', { text, tag, voice: pick.voice.id || pick.voice.name, rate }, 60000);
      return { ok: !!r.ok, detail: r.detail || pick.voice.name };
    },
  });
  post({ cmd: 'hello' });
  return shell;
}

export function nativeVoices() {
  return voices;
}
