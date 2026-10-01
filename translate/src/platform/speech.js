// Speech roles (spec §2 stages 1 and 5), reached through substitutable
// adapters. On the web build the roles are filled by the platform's own speech
// services; a native shell can register its bundled open-source ASR / TTS
// engines with registerAsr() / registerTts() without touching the app.
//
// ASR output is UNTRUSTED input: it is shown for confirmation before it is
// translated. TTS never fabricates audio: if no real voice exists for the
// language, speak() refuses with a remedy.

let customAsr = null;
let customTts = null;

export function registerAsr(adapter) { customAsr = adapter; }
export function registerTts(adapter) { customTts = adapter; }

const SR = typeof window !== 'undefined' ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null;

export const asr = {
  get available() {
    return !!(customAsr || SR);
  },
  get provider() {
    if (customAsr) return customAsr.name || 'bundled ASR';
    return SR ? 'device speech service' : 'none';
  },

  /** Whether recognition for this language can run without a network. null = unknown. */
  async onDevice(tag) {
    if (customAsr && customAsr.onDevice) return customAsr.onDevice(tag);
    if (SR && typeof SR.available === 'function') {
      try {
        const status = await SR.available({ langs: [tag], processLocally: true });
        return status === 'available' ? true : status === 'unavailable' ? false : status;
      } catch { return null; }
    }
    return null;
  },

  async installOnDevice(tag) {
    if (SR && typeof SR.install === 'function') {
      try { return await SR.install({ langs: [tag], processLocally: true }); } catch { return false; }
    }
    return false;
  },

  /**
   * Start one utterance. Callbacks: onPartial(text), onFinal({text, confidence}), onError(code, message), onEnd().
   * Returns a stop() function.
   */
  start({ tag, preferOnDevice = true, onPartial, onFinal, onError, onEnd }) {
    if (customAsr) return customAsr.start({ tag, onPartial, onFinal, onError, onEnd });
    if (!SR) { onError && onError('unsupported', 'Speech recognition is not available in this browser — use text mode.'); onEnd && onEnd(); return () => {}; }
    const rec = new SR();
    rec.lang = tag;
    rec.interimResults = true;
    rec.continuous = false;
    rec.maxAlternatives = 1;
    if (preferOnDevice && 'processLocally' in rec) rec.processLocally = true;
    let finalText = '';
    let confidence = null;
    rec.onresult = (ev) => {
      let interim = '';
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const r = ev.results[i];
        if (r.isFinal) { finalText += r[0].transcript; confidence = r[0].confidence || confidence; } else interim += r[0].transcript;
      }
      onPartial && onPartial((finalText + ' ' + interim).trim());
    };
    rec.onerror = (ev) => {
      const messages = {
        network: 'The speech service needs a network on this device. Type instead, or install on-device recognition for this language.',
        'not-allowed': 'Microphone permission was denied.',
        'service-not-allowed': 'Speech recognition is blocked on this device.',
        'no-speech': 'No speech heard.',
        'language-not-supported': `This device cannot recognize ${tag} speech yet — type instead.`,
        'audio-capture': 'No microphone found.',
      };
      onError && onError(ev.error, messages[ev.error] || `Recognition error: ${ev.error}`);
    };
    rec.onend = () => {
      if (finalText.trim()) onFinal && onFinal({ text: finalText.trim(), confidence });
      onEnd && onEnd();
    };
    try { rec.start(); } catch (e) { onError && onError('start', String(e.message || e)); onEnd && onEnd(); }
    return () => { try { rec.stop(); } catch { /* already stopped */ } };
  },
};

function synth() {
  return typeof window !== 'undefined' && window.speechSynthesis ? window.speechSynthesis : null;
}

// Voices are read once at start and again only when the platform says they
// changed. Lookups use this cache: calling getVoices() from a render path can
// re-fire voiceschanged on some engines and loop.
let voiceList = [];
const voiceListeners = new Set();
export function refreshVoices() {
  const s = synth();
  voiceList = s ? s.getVoices() : [];
  return voiceList;
}
export function onVoicesChanged(fn) {
  voiceListeners.add(fn);
}
if (synth()) {
  refreshVoices();
  let pending = null;
  synth().addEventListener?.('voiceschanged', () => {
    clearTimeout(pending);
    pending = setTimeout(() => {
      const before = voiceList.length;
      refreshVoices();
      if (voiceList.length !== before) voiceListeners.forEach((fn) => fn());
    }, 50);
  });
}

/**
 * Voice selection ladder: exact dialect on-device → language on-device →
 * exact dialect network voice → language network voice (only when online and allowed) → refusal.
 */
export function pickVoice(tag, { allowNetwork = true } = {}) {
  if (customTts && customTts.pickVoice) return customTts.pickVoice(tag);
  const voices = voiceList;
  const norm = (t) => (t || '').replace('_', '-').toLowerCase();
  const want = norm(tag);
  const lang = want.split('-')[0];
  const exact = voices.filter((v) => norm(v.lang) === want);
  const sameLang = voices.filter((v) => norm(v.lang).split('-')[0] === lang);
  const local = (list) => list.filter((v) => v.localService);
  const remote = (list) => list.filter((v) => !v.localService);
  const sorted = (list) => [...list].sort((a, b) => (b.default ? 1 : 0) - (a.default ? 1 : 0) || a.name.localeCompare(b.name));
  for (const [list, onDevice] of [[local(exact), true], [local(sameLang), true], [remote(exact), false], [remote(sameLang), false]]) {
    if (!list.length) continue;
    if (!onDevice && !allowNetwork) continue;
    const v = sorted(list)[0];
    return { voice: v, onDevice, exact: norm(v.lang) === want };
  }
  return null;
}

export const tts = {
  get available() {
    return !!(customTts || synth());
  },
  voiceStatus(tag, opts) {
    if (!this.available) return { ok: false, detail: 'No speech engine on this device.' };
    const p = pickVoice(tag, opts);
    if (!p) return { ok: false, detail: `No ${tag} voice installed. Add one in your device's text-to-speech settings; the written translation and pronunciation stay available.` };
    return { ok: true, detail: `${p.voice.name} (${p.voice.lang}, ${p.onDevice ? 'on-device' : 'network voice'})`, onDevice: p.onDevice };
  },
  /** @returns {Promise<{ok:boolean, detail:string}>} */
  speak(text, tag, { rate = 1, allowNetwork = true } = {}) {
    if (customTts) return customTts.speak(text, tag, { rate });
    const s = synth();
    if (!s) return Promise.resolve({ ok: false, detail: 'No speech engine on this device.' });
    const pick = pickVoice(tag, { allowNetwork });
    if (!pick) return Promise.resolve({ ok: false, detail: `No real ${tag} voice is available, so nothing is played (no substitute voice is ever used). Install a ${tag} voice in the device's speech settings.` });
    return new Promise((resolve) => {
      s.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.voice = pick.voice;
      u.lang = pick.voice.lang;
      u.rate = rate;
      u.onend = () => resolve({ ok: true, detail: `${pick.voice.name}${pick.onDevice ? '' : ' (network voice)'}` });
      u.onerror = (e) => resolve({ ok: false, detail: `Speech failed: ${e.error || 'unknown error'}` });
      s.speak(u);
    });
  },
  stop() {
    const s = synth();
    if (s) s.cancel();
  },
  voices() {
    if (customTts && customTts.voices) return customTts.voices();
    return voiceList.map((v) => ({ name: v.name, lang: v.lang, onDevice: v.localService }));
  },
};
