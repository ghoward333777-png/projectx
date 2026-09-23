/* Media library uploader: drag and drop, per-file progress, sequential XHR posts so one bad file
   never blocks the others. Falls back to the plain form submit without JavaScript. */
(function () {
  var form = document.getElementById('mms-upload-form'); if (!form) return;
  var zone = document.getElementById('mms-dropzone'); var input = form.querySelector('input[type=file]'); var progress = document.getElementById('mms-upload-progress');
  var maxMb = parseInt(form.getAttribute('data-max-mb') || '512', 10);
  var queue = [];
  function add(files) { for (var i = 0; i < files.length; i++) queue.push(files[i]); render(); }
  function render() {
    progress.innerHTML = '';
    queue.forEach(function (f, i) {
      var row = document.createElement('div'); row.className = 'upload-row'; row.setAttribute('data-i', i);
      var big = f.size > maxMb * 1024 * 1024;
      row.innerHTML = '<span class="name"></span><span class="size"></span><progress max="100" value="0"></progress><span class="state"></span>';
      row.querySelector('.name').textContent = f.name; row.querySelector('.size').textContent = (f.size / 1048576).toFixed(1) + ' MB';
      row.querySelector('.state').textContent = big ? 'too large' : 'queued';
      progress.appendChild(row);
    });
  }
  ['dragenter', 'dragover'].forEach(function (ev) { zone.addEventListener(ev, function (e) { e.preventDefault(); zone.classList.add('over'); }); });
  ['dragleave', 'drop'].forEach(function (ev) { zone.addEventListener(ev, function (e) { e.preventDefault(); zone.classList.remove('over'); }); });
  zone.addEventListener('drop', function (e) { add(e.dataTransfer.files); });
  input.addEventListener('change', function () { add(input.files); input.value = ''; });
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var csrf = form.querySelector('input[name=_csrf]').value; var priv = form.querySelector('input[name=private]').checked ? '1' : '0';
    var i = 0;
    function next() {
      if (i >= queue.length) { window.location = window.location.pathname + '?notice=' + encodeURIComponent(queue.length + ' file(s) processed. Thumbnails are being generated.'); return; }
      var f = queue[i]; var row = progress.querySelector('[data-i="' + i + '"]'); var bar = row.querySelector('progress'); var state = row.querySelector('.state');
      if (f.size > maxMb * 1048576) { i++; return next(); }
      var fd = new FormData(); fd.append('_csrf', csrf); fd.append('private', priv); fd.append('files[]', f, f.name);
      var xhr = new XMLHttpRequest(); xhr.open('POST', form.action);
      xhr.upload.onprogress = function (ev) { if (ev.lengthComputable) bar.value = Math.round(ev.loaded / ev.total * 100); };
      xhr.onload = function () { state.textContent = xhr.status < 400 ? 'done' : 'failed (' + xhr.status + ')'; bar.value = 100; i++; next(); };
      xhr.onerror = function () { state.textContent = 'failed'; i++; next(); };
      state.textContent = 'uploading'; xhr.send(fd);
    }
    next();
  });
})();
