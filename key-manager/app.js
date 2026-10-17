// Cloud Key Manager — small progressive enhancements. Every page works without it.
(function () {
    'use strict';

    // Copy buttons.
    document.querySelectorAll('[data-copy]').forEach(function (button) {
        button.addEventListener('click', function () {
            var field = document.getElementById(button.getAttribute('data-copy'));
            if (!field) { return; }
            var done = function () { button.textContent = 'Copied ✓'; setTimeout(function () { button.textContent = 'Copy'; }, 1800); };
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(field.value).then(done, function () { field.select(); });
            } else {
                field.select();
                try { document.execCommand('copy'); done(); } catch (e) { /* the text stays selected */ }
            }
        });
    });

    // Confirm before destructive actions.
    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
        form.addEventListener('submit', function (event) {
            if (!window.confirm(form.getAttribute('data-confirm'))) { event.preventDefault(); }
        });
    });

    // Selects that submit their form on change (project picker, time window).
    document.querySelectorAll('select[data-autosubmit]').forEach(function (select) {
        select.addEventListener('change', function () { select.form.submit(); });
    });

    // Filter boxes for tables and checkbox lists.
    var filter = function (input, rows) {
        input.addEventListener('input', function () {
            var needle = input.value.trim().toLowerCase();
            rows().forEach(function (row) {
                row.hidden = needle !== '' && row.textContent.toLowerCase().indexOf(needle) === -1;
            });
        });
    };
    document.querySelectorAll('[data-filter-table]').forEach(function (input) {
        var table = document.getElementById(input.getAttribute('data-filter-table'));
        if (table) { filter(input, function () { return table.querySelectorAll('tbody tr'); }); }
    });
    document.querySelectorAll('[data-filter-list]').forEach(function (input) {
        var list = document.getElementById(input.getAttribute('data-filter-list'));
        if (list) { filter(input, function () { return list.querySelectorAll('label'); }); }
    });

    // Application restriction help text.
    var help = {
        none: 'Anyone who has the key can use it. Fine for quick tests; restrict it before you share an app.',
        browser: 'Websites allowed to use the key, one per line, e.g. https://example.com/* or *.example.com/*',
        server: 'Server IP addresses allowed to use the key, one per line, e.g. 203.0.113.7 or 198.51.100.0/24',
        android: 'One app per line: the package name and its SHA-1 fingerprint, e.g. com.example.app DA:39:A3:EE:…',
        ios: 'iOS bundle IDs allowed to use the key, one per line, e.g. com.example.app'
    };
    document.querySelectorAll('[data-app-type]').forEach(function (select) {
        var box = select.closest('fieldset');
        var values = box.querySelector('[data-app-values]');
        var text = box.querySelector('[data-app-help]');
        var sync = function () {
            values.hidden = select.value === 'none';
            values.required = select.value !== 'none';
            text.textContent = help[select.value] || '';
        };
        select.addEventListener('change', sync);
        sync();
    });
})();
