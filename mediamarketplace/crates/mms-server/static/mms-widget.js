/* MediaMarketplace widget runtime: scroll-triggered animations and countdowns.
   Pure progressive enhancement; widgets render fully without it. */
(function () {
  function init(root) {
    var els = root.querySelectorAll('.mms-anim');
    if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (entries) { entries.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('mms-in'); io.unobserve(e.target); } }); }, { threshold: 0.15 });
      els.forEach(function (el) { if (el.classList.contains('mms-trigger-in-view')) io.observe(el); else el.classList.add('mms-in'); });
    } else els.forEach(function (el) { el.classList.add('mms-in'); });
    root.querySelectorAll('.mms-countdown').forEach(function (el) {
      var until = Date.parse((el.getAttribute('data-until') || '').replace(' ', 'T') + 'Z'); var out = el.querySelector('.mms-countdown-value');
      if (!out || isNaN(until)) return;
      function tick() {
        var d = until - Date.now();
        if (d <= 0) { out.textContent = el.getAttribute('data-expired') || 'Now'; return; }
        var s = Math.floor(d / 1000), days = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
        out.textContent = (days ? days + 'd ' : '') + String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
        setTimeout(tick, 1000);
      }
      tick();
    });
  }
  window.mmsWidgetInit = init;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { init(document); }); else init(document);
})();
