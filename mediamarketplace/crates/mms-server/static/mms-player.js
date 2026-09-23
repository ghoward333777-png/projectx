/* MediaMarketplace universal player <mms-player>.
   Attributes: type=video|audio, src, poster, base (mount path),
   player=native|plyr|videojs|clappr|vimeo|jwplayer|bitmovin|theoplayer|kaltura|flowplayer|projekktor
   (licensed players load from their vendor CDN with the key configured under Settings → Players),
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
      var cfg = (window.MMS_PLAYERS || {});
      if (kind === 'plyr') { css.href = base + '/static/vendor/plyr.css'; js.src = base + '/static/vendor/plyr.min.js'; }
      else if (kind === 'videojs') { css.href = base + '/static/vendor/video-js.min.css'; js.src = base + '/static/vendor/video.min.js'; }
      else if (kind === 'clappr') { js.src = base + '/static/vendor/clappr.min.js'; css = null; }
      else if (kind === 'vimeo') { js.src = base + '/static/vendor/vimeo-player.min.js'; css = null; }
      else if (kind === 'jwplayer') { js.src = cfg.jwplayer_library || ''; css = null; }
      else if (kind === 'bitmovin') { js.src = 'https://cdn.bitmovin.com/player/web/8/bitmovinplayer.js'; css = null; }
      else if (kind === 'theoplayer') { js.src = (cfg.theoplayer_library || 'https://cdn.theoplayer.com/dash/theoplayer/THEOplayer.js'); css.href = (cfg.theoplayer_library || 'https://cdn.theoplayer.com/dash/theoplayer/').replace(/THEOplayer\.js$/, '') + 'ui.css'; }
      else if (kind === 'kaltura') { js.src = 'https://cdnapisec.kaltura.com/p/' + (cfg.kaltura_partner || '0') + '/embedPlaykitJs/uiconf_id/' + (cfg.kaltura_uiconf || '0'); css = null; }
      else if (kind === 'flowplayer') { js.src = 'https://cdn.flowplayer.com/releases/native/stable/flowplayer.min.js'; css.href = 'https://cdn.flowplayer.com/releases/native/stable/style/flowplayer.css'; }
      else if (kind === 'projekktor') { js.src = (cfg.projekktor_library || ''); css = null; }
      if (!js.src) { resolve(); return; }
      js.onload = resolve; js.onerror = resolve;
      if (css) document.head.appendChild(css); document.head.appendChild(js);
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
      } else if (wanted === 'clappr' && type === 'video') {
        load('clappr', base).then(function () { if (window.Clappr) { try { var box = document.createElement('div'); wrap.insertBefore(box, el); el.style.display = 'none'; self2._clappr = new Clappr.Player({ source: el.src, poster: el.poster || undefined, parentId: null, parent: box, width: '100%', height: 'auto' }); self2.setAttribute('data-player', 'clappr'); } catch (e) { el.style.display = ''; fallback('Clappr failed'); } } else fallback('Clappr not loaded'); });
      } else if (wanted === 'vimeo' && type === 'video') {
        // For media hosted on Vimeo (src is a vimeo.com link); local files fall back to native.
        if (/vimeo\.com\//.test(el.src)) { load('vimeo', base).then(function () { if (window.Vimeo) { try { var box = document.createElement('div'); wrap.insertBefore(box, el); el.style.display = 'none'; self2._vimeo = new Vimeo.Player(box, { url: el.src, responsive: true }); self2.setAttribute('data-player', 'vimeo'); } catch (e) { el.style.display = ''; fallback('Vimeo failed'); } } else fallback('Vimeo SDK not loaded'); }); } else fallback('Vimeo player needs a vimeo.com source');
      } else if (wanted === 'jwplayer' && type === 'video') {
        load('jwplayer', base).then(function () { var cfg = window.MMS_PLAYERS || {}; if (window.jwplayer && cfg.jwplayer_key) { try { var box = document.createElement('div'); box.id = 'mms-jw-' + Math.random().toString(36).slice(2); wrap.insertBefore(box, el); el.style.display = 'none'; jwplayer.key = cfg.jwplayer_key; jwplayer(box.id).setup({ file: el.src, image: el.poster || undefined, width: '100%', aspectratio: '16:9' }); self2.setAttribute('data-player', 'jwplayer'); } catch (e) { el.style.display = ''; fallback('JW Player failed'); } } else fallback('JW Player needs its library URL and key under Settings → Players'); });
      } else if (wanted === 'bitmovin' && type === 'video') {
        load('bitmovin', base).then(function () { var cfg = window.MMS_PLAYERS || {}; if (window.bitmovin && cfg.bitmovin_key) { try { var box = document.createElement('div'); wrap.insertBefore(box, el); el.style.display = 'none'; var bp = new bitmovin.player.Player(box, { key: cfg.bitmovin_key }); bp.load({ progressive: el.src, poster: el.poster || undefined }); self2._bitmovin = bp; self2.setAttribute('data-player', 'bitmovin'); } catch (e) { el.style.display = ''; fallback('Bitmovin failed'); } } else fallback('Bitmovin needs its licence key under Settings → Players'); });
      } else if (wanted === 'theoplayer' && type === 'video') {
        load('theoplayer', base).then(function () { var cfg = window.MMS_PLAYERS || {}; if (window.THEOplayer && cfg.theoplayer_license) { try { var box = document.createElement('div'); box.className = 'theoplayer-container video-js theoplayer-skin'; wrap.insertBefore(box, el); el.style.display = 'none'; var tp = new THEOplayer.Player(box, { license: cfg.theoplayer_license, libraryLocation: (cfg.theoplayer_library || 'https://cdn.theoplayer.com/dash/theoplayer/').replace(/THEOplayer\.js$/, '') }); tp.source = { sources: [{ src: el.src }], poster: el.poster || undefined }; self2._theo = tp; self2.setAttribute('data-player', 'theoplayer'); } catch (e) { el.style.display = ''; fallback('THEOplayer failed'); } } else fallback('THEOplayer needs its licence under Settings → Players'); });
      } else if (wanted === 'kaltura' && type === 'video') {
        load('kaltura', base).then(function () { var cfg = window.MMS_PLAYERS || {}; if (window.KalturaPlayer && cfg.kaltura_partner) { try { var box = document.createElement('div'); box.id = 'mms-kaltura-' + Math.random().toString(36).slice(2); wrap.insertBefore(box, el); el.style.display = 'none'; var kp = KalturaPlayer.setup({ targetId: box.id, provider: { partnerId: cfg.kaltura_partner, uiConfId: cfg.kaltura_uiconf } }); kp.setMedia({ sources: { progressive: [{ url: el.src, mimetype: 'video/mp4' }], poster: el.poster || undefined } }); self2._kaltura = kp; self2.setAttribute('data-player', 'kaltura'); } catch (e) { el.style.display = ''; fallback('Kaltura failed'); } } else fallback('Kaltura needs partner and UI conf ids under Settings → Players'); });
      } else if (wanted === 'flowplayer' && type === 'video') {
        load('flowplayer', base).then(function () { var cfg = window.MMS_PLAYERS || {}; if (window.flowplayer && cfg.flowplayer_token) { try { var box = document.createElement('div'); wrap.insertBefore(box, el); el.style.display = 'none'; self2._flow = flowplayer(box, { src: el.src, poster: el.poster || undefined, token: cfg.flowplayer_token }); self2.setAttribute('data-player', 'flowplayer'); } catch (e) { el.style.display = ''; fallback('Flowplayer failed'); } } else fallback('Flowplayer needs its token under Settings → Players'); });
      } else if (wanted === 'projekktor' && type === 'video') {
        load('projekktor', base).then(function () { if (window.projekktor) { try { self2._pp = projekktor(el, { width: '100%', height: 'auto', playerFlashMP4: '', poster: el.poster || undefined }); self2.setAttribute('data-player', 'projekktor'); } catch (e) { fallback('Projekktor failed'); } } else fallback('Projekktor needs its library URL under Settings → Players'); });
      } else fallback('');
      this.media = el;
    }
    play() { return this.media && this.media.play(); }
    pause() { this.media && this.media.pause(); }
    seek(s) { if (this.media) this.media.currentTime = s; }
  }
  customElements.define('mms-player', MmsPlayer);
})();
