/* MediaMarketplace widget builder. No framework, no build step.
   State is one definition tree; every edit goes through commit() which records undo history and re-renders. */
(function () {
  var D = JSON.parse(document.getElementById('bb-data').textContent);
  var base = D.base, csrf = D.csrf, uuid = D.uuid;
  var def = JSON.parse(D.definition);
  var schema = {}; D.components.forEach(function (c) { schema[c.kind] = c; });
  var history = [], future = [], selected = null, counter = 0, dirty = false, previewTimer = null;
  var frame = document.getElementById('bb-frame'), layers = document.getElementById('bb-layers'), props = document.getElementById('bb-props');
  var toast = document.createElement('div'); toast.className = 'bb-toast'; document.body.appendChild(toast);
  function say(msg) { toast.textContent = msg; toast.classList.add('on'); setTimeout(function () { toast.classList.remove('on'); }, 1800); }

  // ----- tree helpers -----
  function ensureIds(node) { if (!node.id) node.id = 'c' + (++counter); node.children = node.children || []; node.props = node.props || {}; node.children.forEach(ensureIds); var n = parseInt(String(node.id).replace(/\D/g, ''), 10); if (n > counter) counter = n; }
  function find(id, node, parent) { node = node || def.root; if (node.id === id) return { node: node, parent: parent }; for (var i = 0; i < node.children.length; i++) { var r = find(id, node.children[i], node); if (r) return r; } return null; }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function commit(label) { history.push(clone(def)); if (history.length > 50) history.shift(); future = []; dirty = true; refresh(); if (label) say(label); }
  function undo() { if (!history.length) return; future.push(clone(def)); def = history.pop(); refresh(); }
  function redo() { if (!future.length) return; history.push(clone(def)); def = future.pop(); refresh(); }
  function newComponent(kind) { var c = { id: 'c' + (++counter), kind: kind, props: {}, children: [] }; (schema[kind] ? schema[kind].fields : []).forEach(function (f) { c.props[f.key] = f.kind === 'bool' ? f.default === 'true' : (f.kind === 'number' ? Number(f.default) : f.default); }); if (kind === 'container') c.props.layout = 'stack'; return c; }
  function addInto(kind, targetId, position) {
    var c = newComponent(kind); var t = targetId ? find(targetId) : null;
    if (!t) { def.root.children.push(c); }
    else if (t.node.kind === 'container' && position === 'inside') { t.node.children.push(c); }
    else { var idx = t.parent.children.indexOf(t.node); t.parent.children.splice(position === 'before' ? idx : idx + 1, 0, c); }
    selected = c.id; commit('Added ' + kind);
  }
  function move(id, targetId, position) {
    if (id === targetId || id === 'root') return; var s = find(id); var t = find(targetId); if (!s || !t) return;
    var inside = find(targetId, s.node); if (inside && position === 'inside') return; // no dropping into itself
    if (find(targetId, s.node) && targetId !== id) return;
    s.parent.children.splice(s.parent.children.indexOf(s.node), 1);
    if (t.node.kind === 'container' && position === 'inside') t.node.children.push(s.node);
    else { var idx = t.parent.children.indexOf(t.node); t.parent.children.splice(position === 'before' ? idx : idx + 1, 0, s.node); }
    commit('Moved');
  }
  function shift(id, delta) { var s = find(id); if (!s || !s.parent) return; var i = s.parent.children.indexOf(s.node), j = i + delta; if (j < 0 || j >= s.parent.children.length) return; s.parent.children.splice(i, 1); s.parent.children.splice(j, 0, s.node); commit(); }
  function remove(id) { var s = find(id); if (!s || !s.parent) return; s.parent.children.splice(s.parent.children.indexOf(s.node), 1); selected = s.parent.id; commit('Removed'); }
  function duplicate(id) { var s = find(id); if (!s || !s.parent) return; var c = clone(s.node); (function reid(n) { n.id = 'c' + (++counter); n.children.forEach(reid); })(c); s.parent.children.splice(s.parent.children.indexOf(s.node) + 1, 0, c); selected = c.id; commit('Duplicated'); }

  // ----- rendering -----
  function refresh() { renderLayers(); renderProps(); schedulePreview(); }
  function label(n) { var t = n.props && (n.props.text || n.props.label || n.props.title || n.props.product); return (schema[n.kind] ? schema[n.kind].label : n.kind) + (t ? ': ' + String(t).slice(0, 22) : ''); }
  function renderLayers() {
    layers.innerHTML = '';
    (function walk(node, ol) {
      var li = document.createElement('li'); li.setAttribute('data-id', node.id); li.draggable = node.id !== 'root'; li.tabIndex = 0;
      li.innerHTML = '<span></span><span class="k"></span>'; li.firstChild.textContent = label(node); li.lastChild.textContent = node.kind === 'container' ? (node.props.layout || 'stack') : '';
      if (node.id === selected) li.classList.add('on');
      li.addEventListener('click', function (e) { e.stopPropagation(); selected = node.id; refresh(); });
      li.addEventListener('dragstart', function (e) { e.dataTransfer.setData('text/mms-move', node.id); e.stopPropagation(); });
      li.addEventListener('dragover', function (e) { e.preventDefault(); e.stopPropagation(); li.classList.add('drop'); });
      li.addEventListener('dragleave', function () { li.classList.remove('drop'); });
      li.addEventListener('drop', function (e) {
        e.preventDefault(); e.stopPropagation(); li.classList.remove('drop');
        var rect = li.getBoundingClientRect(); var pos = node.kind === 'container' ? 'inside' : (e.clientY < rect.top + rect.height / 2 ? 'before' : 'after');
        var kind = e.dataTransfer.getData('text/mms-kind'); var mv = e.dataTransfer.getData('text/mms-move');
        if (kind) addInto(kind, node.id, pos); else if (mv) move(mv, node.id, pos);
      });
      ol.appendChild(li);
      if (node.children.length) { var sub = document.createElement('ol'); walk2(node, sub); ol.appendChild(sub); }
    })(def.root, layers);
    function walk2(node, ol) { node.children.forEach(function (c) { (function walk(node, ol) { var li = layers.querySelector('[data-id="' + node.id + '"]'); })(c, ol); }); }
    // second pass builds nested lists properly
    layers.innerHTML = '';
    (function build(node, ol) {
      var li = document.createElement('li'); li.setAttribute('data-id', node.id); li.draggable = node.id !== 'root'; li.tabIndex = 0;
      var a = document.createElement('span'); a.textContent = label(node); var b = document.createElement('span'); b.className = 'k'; b.textContent = node.kind === 'container' ? (node.props.layout || 'stack') : ''; li.appendChild(a); li.appendChild(b);
      if (node.id === selected) li.classList.add('on');
      li.addEventListener('click', function (e) { e.stopPropagation(); selected = node.id; refresh(); });
      li.addEventListener('dragstart', function (e) { e.dataTransfer.setData('text/mms-move', node.id); e.stopPropagation(); });
      li.addEventListener('dragover', function (e) { e.preventDefault(); e.stopPropagation(); li.classList.add('drop'); });
      li.addEventListener('dragleave', function () { li.classList.remove('drop'); });
      li.addEventListener('drop', function (e) { e.preventDefault(); e.stopPropagation(); li.classList.remove('drop'); var rect = li.getBoundingClientRect(); var pos = node.kind === 'container' ? 'inside' : (e.clientY < rect.top + rect.height / 2 ? 'before' : 'after'); var kind = e.dataTransfer.getData('text/mms-kind'); var mv = e.dataTransfer.getData('text/mms-move'); if (kind) addInto(kind, node.id, pos); else if (mv) move(mv, node.id, pos); });
      ol.appendChild(li);
      if (node.children.length) { var sub = document.createElement('ol'); node.children.forEach(function (c) { build(c, sub); }); ol.appendChild(sub); }
    })(def.root, layers);
  }
  function field(labelText, input) { var l = document.createElement('label'); l.textContent = labelText; l.appendChild(input); return l; }
  function renderProps() {
    props.innerHTML = '';
    var s = selected ? find(selected) : null; if (!s) { props.innerHTML = '<p class="muted">Select a component in the layer tree or on the canvas.</p>'; document.getElementById('bb-props-title').textContent = 'Properties'; return; }
    var node = s.node; document.getElementById('bb-props-title').textContent = (schema[node.kind] ? schema[node.kind].label : node.kind) + (node.id === 'root' ? ' (root)' : '');
    var actions = document.createElement('div'); actions.className = 'actions';
    if (node.id !== 'root') {
      [['↑ Up', function () { shift(node.id, -1); }], ['↓ Down', function () { shift(node.id, 1); }], ['Duplicate', function () { duplicate(node.id); }], ['Delete', function () { remove(node.id); }, 'danger']].forEach(function (a) { var b = document.createElement('button'); b.textContent = a[0]; if (a[2]) b.className = a[2]; b.addEventListener('click', a[1]); actions.appendChild(b); });
    }
    if (node.kind === 'container') { var add = document.createElement('select'); add.innerHTML = '<option value="">＋ Add inside…</option>' + D.components.map(function (c) { return '<option value="' + c.kind + '">' + c.label + '</option>'; }).join(''); add.addEventListener('change', function () { if (add.value) addInto(add.value, node.id, 'inside'); }); actions.appendChild(add); }
    props.appendChild(actions);
    (schema[node.kind] ? schema[node.kind].fields : []).forEach(function (f) {
      var v = node.props[f.key]; if (v === undefined) v = f.default; var input;
      if (f.kind === 'textarea') { input = document.createElement('textarea'); input.rows = 3; input.value = v; }
      else if (f.kind === 'bool') { input = document.createElement('input'); input.type = 'checkbox'; input.checked = v === true || v === 'true'; }
      else if (f.kind === 'number') { input = document.createElement('input'); input.type = 'number'; input.value = v; }
      else if (f.kind === 'color') { input = document.createElement('input'); input.type = 'text'; input.placeholder = '#336699 or empty'; input.value = v; }
      else if (f.kind.indexOf('select:') === 0) { input = document.createElement('select'); f.kind.slice(7).split(',').forEach(function (o) { var op = document.createElement('option'); op.value = o; op.textContent = o; if (o === v) op.selected = true; input.appendChild(op); }); }
      else if (f.kind === 'media') { input = document.createElement('select'); input.innerHTML = '<option value="">— none —</option>'; D.media.forEach(function (m) { var op = document.createElement('option'); op.value = m.uuid; op.textContent = (m.title || m.uuid) + ' (' + m.type + ')'; if (m.uuid === v) op.selected = true; input.appendChild(op); }); }
      else if (f.kind === 'product') { input = document.createElement('select'); input.innerHTML = '<option value="">— none —</option>'; D.products.forEach(function (p) { var op = document.createElement('option'); op.value = p.slug; op.textContent = p.title; if (p.slug === v) op.selected = true; input.appendChild(op); }); }
      else { input = document.createElement('input'); input.type = 'text'; input.value = v; }
      input.addEventListener('change', function () { node.props[f.key] = f.kind === 'bool' ? input.checked : (f.kind === 'number' ? Number(input.value) : input.value); commit(); });
      if (f.kind === 'textarea' || (input.type === 'text')) input.addEventListener('input', function () { node.props[f.key] = input.value; dirty = true; schedulePreview(); });
      props.appendChild(field(f.label, input));
    });
    // animation
    var an = document.createElement('details'); an.innerHTML = '<summary>Animation</summary>'; var a = node.animation || { name: 'none', trigger: 'in-view', duration_ms: 600, delay_ms: 0, easing: 'ease-out' };
    var sel = document.createElement('select'); D.animations.forEach(function (n) { var o = document.createElement('option'); o.value = n; o.textContent = n; if (n === a.name) o.selected = true; sel.appendChild(o); });
    var trig = document.createElement('select'); ['in-view', 'load', 'hover'].forEach(function (n) { var o = document.createElement('option'); o.value = n; o.textContent = n; if (n === a.trigger) o.selected = true; trig.appendChild(o); });
    var dur = document.createElement('input'); dur.type = 'number'; dur.value = a.duration_ms; var del = document.createElement('input'); del.type = 'number'; del.value = a.delay_ms;
    var eas = document.createElement('select'); ['ease-out', 'ease', 'ease-in', 'ease-in-out', 'linear'].forEach(function (n) { var o = document.createElement('option'); o.value = n; o.textContent = n; if (n === a.easing) o.selected = true; eas.appendChild(o); });
    [sel, trig, dur, del, eas].forEach(function (i) { i.addEventListener('change', function () { node.animation = { name: sel.value, trigger: trig.value, duration_ms: Number(dur.value), delay_ms: Number(del.value), easing: eas.value }; if (sel.value === 'none') node.animation = null; commit(); }); });
    an.appendChild(field('Effect', sel)); an.appendChild(field('Trigger', trig)); an.appendChild(field('Duration (ms)', dur)); an.appendChild(field('Delay (ms)', del)); an.appendChild(field('Easing', eas)); props.appendChild(an);
    // responsive
    ['tablet', 'mobile'].forEach(function (bp) {
      var d = document.createElement('details'); d.innerHTML = '<summary>' + (bp === 'tablet' ? 'Tablet (≤ 1024px)' : 'Phone (≤ 640px)') + '</summary>'; var r = node[bp] || {};
      var hid = document.createElement('input'); hid.type = 'checkbox'; hid.checked = !!r.hidden;
      var w = document.createElement('input'); w.placeholder = 'e.g. 50%'; w.value = r.width || ''; var al = document.createElement('select'); ['', 'left', 'center', 'right'].forEach(function (n) { var o = document.createElement('option'); o.value = n; o.textContent = n || 'inherit'; if (n === (r.align || '')) o.selected = true; al.appendChild(o); });
      var fs = document.createElement('input'); fs.placeholder = 'px'; fs.value = r.font_size || ''; var pd = document.createElement('input'); pd.placeholder = 'px'; pd.value = r.padding || '';
      [hid, w, al, fs, pd].forEach(function (i) { i.addEventListener('change', function () { node[bp] = { hidden: hid.checked, width: w.value, align: al.value, font_size: fs.value, padding: pd.value }; commit(); }); });
      d.appendChild(field('Hidden', hid)); d.appendChild(field('Width', w)); d.appendChild(field('Text align', al)); d.appendChild(field('Font size', fs)); d.appendChild(field('Padding', pd)); props.appendChild(d);
    });
  }
  function currentTheme() { return document.getElementById('bb-theme').value; }
  function currentScheme() { return document.getElementById('bb-scheme').value; }
  function schedulePreview() { clearTimeout(previewTimer); previewTimer = setTimeout(preview, 100); }
  function preview() {
    fetch(base + '/api/v1/widgets/' + uuid + '/preview', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ definition: def, custom_css: document.getElementById('bb-css').value, theme: currentTheme(), scheme: currentScheme() }) })
      .then(function (r) { return r.json(); }).then(function (j) {
        if (j.error) { say(j.error.message); return; }
        var sel = selected ? '.mms-c-' + selected + '{outline:2px solid #2f5a8c;outline-offset:2px}' : '';
        var doc = '<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="' + base + '/static/mms.css"><style>' + j.data.css + sel + ' .mms-c{cursor:pointer} body{margin:0;padding:8px} .bb-drop{outline:2px dashed #a86400 !important}</style></head><body class="embed">' + j.data.html + '<script src="' + base + '/static/mms-player.js"><\/script><script src="' + base + '/static/mms-widget.js"><\/script></body></html>';
        frame.srcdoc = doc;
        frame.onload = function () {
          var d = frame.contentDocument; if (!d) return;
          d.addEventListener('click', function (e) { var el = e.target.closest('.mms-c'); if (!el) return; e.preventDefault(); var m = /mms-c-([A-Za-z0-9_-]+)/.exec(el.className); if (m) { selected = m[1]; renderLayers(); renderProps(); d.querySelectorAll('.bb-sel').forEach(function (x) { x.classList.remove('bb-sel'); }); el.style.outline = '2px solid #2f5a8c'; } });
          d.addEventListener('dblclick', function (e) { var el = e.target.closest('.mms-text'); if (!el) return; var m = /mms-c-([A-Za-z0-9_-]+)/.exec(el.className); if (!m) return; el.contentEditable = 'true'; el.focus(); el.addEventListener('blur', function () { el.contentEditable = 'false'; var s = find(m[1]); if (s) { s.node.props.text = el.innerText; commit('Text updated'); } }, { once: true }); });
          d.addEventListener('dragover', function (e) { e.preventDefault(); var el = e.target.closest('.mms-c'); d.querySelectorAll('.bb-drop').forEach(function (x) { x.classList.remove('bb-drop'); }); if (el) el.classList.add('bb-drop'); });
          d.addEventListener('drop', function (e) { e.preventDefault(); var el = e.target.closest('.mms-c'); var kind = e.dataTransfer.getData('text/mms-kind'); var mv = e.dataTransfer.getData('text/mms-move'); var id = el ? (/mms-c-([A-Za-z0-9_-]+)/.exec(el.className) || [])[1] : null; var pos = 'after'; if (id) { var t = find(id); if (t && t.node.kind === 'container') pos = 'inside'; else if (el) { var r = el.getBoundingClientRect(); pos = e.clientY < r.top + r.height / 2 ? 'before' : 'after'; } } if (kind) addInto(kind, id, pos); else if (mv && id) move(mv, id, pos); });
          frame.style.height = Math.max(400, d.documentElement.scrollHeight + 20) + 'px';
        };
      }).catch(function () { say('Preview failed'); });
  }

  // ----- palette drag and keyboard -----
  document.querySelectorAll('#bb-palette li').forEach(function (li) {
    li.addEventListener('dragstart', function (e) { e.dataTransfer.setData('text/mms-kind', li.getAttribute('data-kind')); });
    li.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); var s = selected ? find(selected) : null; addInto(li.getAttribute('data-kind'), s && s.node.kind === 'container' ? s.node.id : (s ? s.node.id : null), s && s.node.kind === 'container' ? 'inside' : 'after'); } });
    li.addEventListener('dblclick', function () { addInto(li.getAttribute('data-kind'), selected, selected && find(selected).node.kind === 'container' ? 'inside' : 'after'); });
  });
  document.addEventListener('keydown', function (e) {
    var inField = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); }
    else if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'y' || (e.shiftKey && e.key.toLowerCase() === 'z'))) { e.preventDefault(); redo(); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); save(); }
    else if (!inField && selected) {
      if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); remove(selected); }
      else if (e.altKey && e.key === 'ArrowUp') { e.preventDefault(); shift(selected, -1); }
      else if (e.altKey && e.key === 'ArrowDown') { e.preventDefault(); shift(selected, 1); }
      else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { e.preventDefault(); var items = Array.prototype.slice.call(layers.querySelectorAll('li')); var i = items.findIndex(function (li) { return li.getAttribute('data-id') === selected; }); var n = items[i + (e.key === 'ArrowDown' ? 1 : -1)]; if (n) { selected = n.getAttribute('data-id'); refresh(); } }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'd') { e.preventDefault(); duplicate(selected); }
    }
  });

  // ----- toolbar -----
  document.getElementById('bb-undo').addEventListener('click', undo); document.getElementById('bb-redo').addEventListener('click', redo);
  document.querySelectorAll('.bb-devices button').forEach(function (b) { b.addEventListener('click', function () { document.querySelectorAll('.bb-devices button').forEach(function (x) { x.classList.remove('on'); }); b.classList.add('on'); document.getElementById('bb-canvas').style.width = b.getAttribute('data-w'); }); });
  ['bb-theme', 'bb-scheme'].forEach(function (id) { document.getElementById(id).addEventListener('change', function () { dirty = true; schedulePreview(); }); });
  document.getElementById('bb-css').addEventListener('input', function () { dirty = true; schedulePreview(); });
  document.getElementById('bb-export').addEventListener('click', function () { document.getElementById('bb-export-dialog').showModal(); });
  document.getElementById('bb-preview').addEventListener('click', function () { window.open(base + '/embed/widget/' + uuid + '?site=' + encodeURIComponent(D.site), '_blank'); });
  function save() {
    fetch(base + '/api/v1/widgets/' + uuid, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-MMS-CSRF': csrf }, body: JSON.stringify({ name: document.getElementById('bb-name').value, definition: def, custom_css: document.getElementById('bb-css').value, theme: currentTheme(), scheme: currentScheme(), status: document.getElementById('bb-state').value }) })
      .then(function (r) { return r.json(); }).then(function (j) { if (j.error) { say('Not saved: ' + j.error.message); return; } dirty = false; document.getElementById('bb-status').textContent = 'v' + j.data.version + ' · ' + j.data.status; say('Saved'); }).catch(function () { say('Save failed'); });
  }
  document.getElementById('bb-save').addEventListener('click', save);
  window.addEventListener('beforeunload', function (e) { if (dirty) { e.preventDefault(); e.returnValue = ''; } });

  ensureIds(def.root); selected = def.root.children.length ? def.root.children[0].id : 'root'; refresh();
})();
