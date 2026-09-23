/* MediaMarketplace universal player <mms-player>.
   Attributes: type=video|audio, src, poster, player=native|plyr|videojs, base (mount path),
   product (slug, enables playback sessions), start/clip (free preview window in seconds),
   watermark (text overlay, Level 1 visible watermark). */
(function () {
  if (customElements.get('mms-player')) return;
  var loaded = {};
  function load(kind, base) {
    if (loaded[kind]) return loaded[kind];
    loaded[kind] = new Promise(function (resolve) {
      var css = document.createElement('link'); css.rel = 'stylesheet';
      var js = document.createElement('script');
      if (kind === 'plyr') { css.href = base + '/static/vendor/plyr.css'; js.src = base + '/static/vendor/plyr.min.js'; }
      else { css.href = base + '/static/vendor/video-js.min.css'; js.src = base + '/static/vendor/video.min.js'; }
      js.onload = resolve; js.onerror = resolve;
      document.head.appendChild(css); document.head.appendChild(js);
    });
    return loaded[kind];
  }
  function api(base, path, body) {
    return fetch(base + '/api/v1/playback/' + path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (r) { return r.json(); }).catch(function () { return {}; });
  }
  class MmsPlayer extends HTMLElement {
    connectedCallback() {
      var self = this;
      var type = this.getAttribute('type') === 'audio' ? 'audio' : 'video';
      var base = this.getAttribute('base') || '';
      var wanted = this.getAttribute('player') || 'native';
      var el = document.createElement(type);
      el.controls = true; el.preload = 'metadata'; el.setAttribute('playsinline', '');
      el.src = this.getAttribute('src') || '';
      if (this.getAttribute('poster')) el.poster = this.getAttribute('poster');
      el.className = wanted === 'videojs' ? 'video-js vjs-big-play-centered' : '';
      var wrap = document.createElement('div'); wrap.className = 'mms-player-wrap';
      wrap.appendChild(el);
      this.innerHTML = ''; this.appendChild(wrap);
      // Level 1 visible watermark: re-asserted if removed.
      var wm = this.getAttribute('watermark');
      if (wm && type === 'video') {
        var overlay = document.createElement('div'); overlay.className = 'mms-watermark'; overlay.textContent = wm;
        wrap.appendChild(overlay);
        new MutationObserver(function () { if (!wrap.contains(overlay)) wrap.appendChild(overlay); }).observe(wrap, { childList: true });
      }
      // Free preview window.
      var start = parseFloat(this.getAttribute('start') || '0') || 0;
      var clip = parseFloat(this.getAttribute('clip') || '0') || 0;
      if (clip > 0) {
        el.addEventListener('loadedmetadata', function () { if (start > 0) el.currentTime = start; });
        el.addEventListener('timeupdate', function () { if (el.currentTime >= start + clip) { el.pause(); el.currentTime = start; self.dispatchEvent(new CustomEvent('mms:preview-ended')); } });
      }
      // Playback sessions for analytics.
      var product = this.getAttribute('product'); var session = null; var timer = null;
      function beat(ended) { if (session) api(base, 'heartbeat', { session: session, position_ms: Math.round(el.currentTime * 1000), duration_ms: isFinite(el.duration) ? Math.round(el.duration * 1000) : null, ended: !!ended }); }
      if (product) {
        el.addEventListener('play', function () {
          if (!session) api(base, 'session', { product: product, player: wanted }).then(function (j) { session = j.data && j.data.session; });
          if (!timer) timer = setInterval(beat, 30000);
        });
        el.addEventListener('pause', function () { beat(false); });
        el.addEventListener('ended', function () { beat(true); clearInterval(timer); timer = null; });
        window.addEventListener('pagehide', function () { beat(false); });
      }
      var self2 = this;
      function fallback(reason) { self2.setAttribute('data-player', 'native'); if (reason) console.warn('mms-player: ' + reason + '; using native controls'); }
      if (wanted === 'plyr') {
        load('plyr', base).then(function () { if (window.Plyr) { try { self2._plyr = new Plyr(el, { iconUrl: base + '/static/vendor/plyr.svg', blankVideo: '' }); self2.setAttribute('data-player', 'plyr'); } catch (e) { fallback('Plyr failed'); } } else fallback('Plyr not loaded'); });
      } else if (wanted === 'videojs') {
        load('videojs', base).then(function () { if (window.videojs) { try { self2._vjs = videojs(el, { fluid: type === 'video' }); self2.setAttribute('data-player', 'videojs'); } catch (e) { fallback('Video.js failed'); } } else fallback('Video.js not loaded'); });
      } else fallback('');
      this.media = el;
    }
    play() { return this.media && this.media.play(); }
    pause() { this.media && this.media.pause(); }
    seek(s) { if (this.media) this.media.currentTime = s; }
  }
  customElements.define('mms-player', MmsPlayer);
})();
