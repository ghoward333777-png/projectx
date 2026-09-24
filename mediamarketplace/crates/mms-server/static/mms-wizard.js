// The form assistant drawer: asks the store's wizard about the current admin page and
// shows the answer with one-click proposals. Loaded on every admin page.
(function () {
  var root = document.getElementById('mms-wizard'); if (!root) return;
  var base = root.getAttribute('data-base') || ''; var csrf = root.getAttribute('data-csrf') || '';
  var page = (root.getAttribute('data-page') || '') + (location.hash || '');
  var panel = root.querySelector('.wz-panel'); var out = root.querySelector('.wz-out'); var form = root.querySelector('form'); var input = form.querySelector('textarea'); var btn = form.querySelector('button');
  root.querySelector('.wz-toggle').addEventListener('click', function () { root.classList.toggle('open'); if (root.classList.contains('open')) input.focus(); });
  root.querySelector('.wz-close').addEventListener('click', function () { root.classList.remove('open'); });
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function render(data) {
    out.innerHTML = '';
    if (data.error && !data.answer) { out.appendChild(el('p', 'error', data.error)); return; }
    (data.answer || '').split('\n').forEach(function (line) { if (line.trim()) out.appendChild(el('p', null, line)); });
    if (data.error) out.appendChild(el('p', 'error small', data.error));
    (data.proposals || []).forEach(function (p) {
      var card = el('div', 'proposal proposed'); card.appendChild(el('div', 'proposal-head', p.title));
      if (p.reason) card.appendChild(el('p', 'small', p.reason));
      if (p.kind === 'setting' && !p.needs_input) card.appendChild(el('p', 'small', p.payload.key + ' → ' + p.payload.value));
      var row = el('div');
      var secret = null; if (p.needs_input) { secret = el('input'); secret.type = 'password'; secret.placeholder = 'Type the ' + (p.payload.label || 'value'); row.appendChild(secret); }
      var apply = el('button', 'primary', 'Apply'); row.appendChild(apply); card.appendChild(row);
      apply.addEventListener('click', function () {
        apply.disabled = true; var body = new URLSearchParams({ _csrf: csrf, _format: 'json' }); if (secret) body.set('value', secret.value);
        fetch(base + '/admin/wizards/' + data.session + '/proposals/' + p.uuid + '/apply', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: body.toString() })
          .then(function (r) { return r.json(); }).then(function (j) { row.innerHTML = ''; row.appendChild(el('span', 'badge ' + (j.status === 'applied' ? 'ok' : 'fail'), j.status + ': ' + j.result)); if (j.status === 'applied') card.classList.add('applied'); })
          .catch(function () { apply.disabled = false; });
      });
      out.appendChild(card);
    });
    var link = el('a', 'small', 'Open this session'); link.href = base + '/admin/wizards/' + data.session; out.appendChild(link);
  }
  form.addEventListener('submit', function (ev) {
    ev.preventDefault(); var q = input.value.trim(); if (!q) return;
    btn.disabled = true; out.innerHTML = ''; out.appendChild(el('p', 'muted small', 'The wizard is reading the page and thinking…'));
    fetch(base + '/admin/wizards/ask', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ page: page, question: q }) })
      .then(function (r) { return r.json(); }).then(render)
      .catch(function (e) { out.innerHTML = ''; out.appendChild(el('p', 'error', 'The wizard could not answer: ' + e)); })
      .then(function () { btn.disabled = false; });
  });
})();
