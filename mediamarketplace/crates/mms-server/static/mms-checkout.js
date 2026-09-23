/* Checkout: gateway card forms that tokenise in the browser (Square Web Payments, Authorize.net Accept.js).
   The token goes into the hidden "token" field; the card number never reaches the store. */
(function () {
  var form = document.getElementById('checkout-form'); if (!form) return;
  var sdks = JSON.parse((document.getElementById('checkout-sdks') || { textContent: '{}' }).textContent || '{}');
  var tokenField = form.querySelector('input[name=token]');
  var submit = form.querySelector('button[type=submit], button.primary');
  var status = document.getElementById('card-status');
  function say(msg, bad) { if (status) { status.textContent = msg || ''; status.className = bad ? 'error small' : 'muted small'; } }
  function chosen() { var r = form.querySelector('input[name=gateway]:checked'); return r ? r.value : ''; }
  function show() { var g = chosen(); document.querySelectorAll('[data-card-for]').forEach(function (el) { el.classList.toggle('hidden', el.getAttribute('data-card-for') !== g); }); }
  form.querySelectorAll('input[name=gateway]').forEach(function (r) { r.addEventListener('change', show); }); show();
  var loaded = {};
  function load(src) { if (loaded[src]) return loaded[src]; loaded[src] = new Promise(function (res, rej) { var s = document.createElement('script'); s.src = src; s.onload = res; s.onerror = rej; document.head.appendChild(s); }); return loaded[src]; }
  var squareCard = null;
  function ensureSquare() {
    var cfg = sdks.square; if (!cfg || squareCard) return Promise.resolve();
    return load(cfg.script).then(function () {
      if (!window.Square) throw new Error('Square SDK did not load');
      return Square.payments(cfg.config.application_id, cfg.config.location_id).card().then(function (card) { squareCard = card; return card.attach('#square-card'); });
    });
  }
  function ensureAuthnet() { var cfg = sdks.authnet; if (!cfg) return Promise.resolve(); return load(cfg.script); }
  form.addEventListener('submit', function (e) {
    var g = chosen();
    if (g !== 'square' && g !== 'authnet') return;
    if (tokenField.value) return; // second pass with the token
    e.preventDefault(); say('Checking your card…'); submit.disabled = true;
    var p;
    if (g === 'square') {
      p = ensureSquare().then(function () { return squareCard.tokenize(); }).then(function (r) { if (r.status !== 'OK') throw new Error((r.errors && r.errors[0] && r.errors[0].message) || 'Card was not accepted'); tokenField.value = r.token; });
    } else {
      p = ensureAuthnet().then(function () {
        var cfg = sdks.authnet.config; var f = function (n) { return (form.querySelector('[name=an_' + n + ']') || {}).value || ''; };
        return new Promise(function (res, rej) {
          Accept.dispatchData({ authData: { clientKey: cfg.client_key, apiLoginID: cfg.login_id }, cardData: { cardNumber: f('number').replace(/\s+/g, ''), month: f('month'), year: f('year'), cardCode: f('cvv') } }, function (r) {
            if (r.messages.resultCode === 'Error') { rej(new Error(r.messages.message.map(function (m) { return m.text; }).join(' '))); return; }
            tokenField.value = r.opaqueData.dataDescriptor + '|' + r.opaqueData.dataValue; res();
          });
        });
      });
    }
    p.then(function () { form.querySelectorAll('[name^=an_]').forEach(function (i) { i.value = ''; }); form.submit(); }).catch(function (err) { say(err.message || String(err), true); submit.disabled = false; });
  });
  document.querySelectorAll('input[name=gateway]').forEach(function (r) { r.addEventListener('change', function () { if (chosen() === 'square') ensureSquare().catch(function (err) { say(err.message, true); }); }); });
  if (chosen() === 'square') ensureSquare().catch(function (err) { say(err.message, true); });
})();
