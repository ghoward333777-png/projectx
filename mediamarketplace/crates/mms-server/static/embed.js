/* MediaMarketplace Studio embed loader. Printed by the bridge plugins.
   Usage: <div data-mms-embed="showcase" data-mms-site="SITE_ID" data-mms-view="grid"></div>
   The server URL is taken from the script's own src. */
(function () {
  var script = document.currentScript || (function () { var s = document.getElementsByTagName('script'); return s[s.length - 1]; })();
  var base = script.getAttribute('data-mms-server') || script.src.replace(/\/embed\.js.*$/, '');
  function mount(el) {
    if (el.getAttribute('data-mms-mounted')) return;
    el.setAttribute('data-mms-mounted', '1');
    var kind = el.getAttribute('data-mms-embed') || 'showcase';
    var params = [];
    var attrs = el.attributes;
    for (var i = 0; i < attrs.length; i++) {
      var a = attrs[i];
      if (a.name.indexOf('data-mms-') === 0 && a.name !== 'data-mms-embed' && a.name !== 'data-mms-mounted') {
        params.push(encodeURIComponent(a.name.slice(9)) + '=' + encodeURIComponent(a.value));
      }
    }
    var frame = document.createElement('iframe');
    frame.src = base + '/embed/' + encodeURIComponent(kind) + (params.length ? '?' + params.join('&') : '');
    frame.style.width = '100%';
    frame.style.border = '0';
    frame.style.minHeight = '200px';
    frame.setAttribute('title', 'MediaMarketplace ' + kind);
    frame.setAttribute('loading', 'lazy');
    frame.setAttribute('allow', 'fullscreen; autoplay; payment');
    el.appendChild(frame);
    window.addEventListener('message', function (ev) {
      if (ev.source === frame.contentWindow && ev.data && ev.data.mms === 'resize' && ev.origin === new URL(base).origin) {
        frame.style.height = ev.data.height + 'px';
      }
    });
  }
  function scan() { var els = document.querySelectorAll('[data-mms-embed]'); for (var i = 0; i < els.length; i++) mount(els[i]); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', scan); else scan();
})();
