// Browser side of the anti-robot shield: fetch a signed puzzle, solve it with
// SHA-256 proof of work, and attach the solution to the form. No tracking, no puzzles to click.
(function () {
    'use strict';

    async function sha256Hex(text) {
        const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
        return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('');
    }

    async function solve(form) {
        const field = form.querySelector('input[name="shield"]');
        const status = form.querySelector('[data-shield-status]');
        const button = form.querySelector('button[type="submit"]');
        field.value = '';
        if (button) button.disabled = true;
        try {
            const response = await fetch('index.php?p=challenge', { cache: 'no-store', credentials: 'same-origin' });
            if (!response.ok) throw new Error('challenge');
            const c = await response.json();
            for (let n = 0; n <= c.max; n++) {
                if ((await sha256Hex(c.salt + n)) === c.challenge) {
                    field.value = btoa(JSON.stringify({ salt: c.salt, challenge: c.challenge, signature: c.signature, number: n }));
                    break;
                }
            }
            if (!field.value) throw new Error('unsolved');
            if (status) { status.textContent = 'Verified: you are not a robot.'; status.classList.add('ok'); }
            // A solution expires after ten minutes; refresh it a little before then.
            setTimeout(function () { solve(form); }, 8 * 60 * 1000);
        } catch (err) {
            if (status) status.textContent = 'The human check could not run. Reload the page to try again.';
        } finally {
            if (button) button.disabled = false;
        }
    }

    document.querySelectorAll('form[data-shield]').forEach(function (form) {
        if (window.crypto && crypto.subtle) {
            solve(form);
        } else {
            const status = form.querySelector('[data-shield-status]');
            if (status) status.textContent = 'This browser cannot run the human check. Please use a current browser over HTTPS.';
        }
    });

    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
        form.addEventListener('submit', function (event) {
            if (!window.confirm(form.dataset.confirm)) event.preventDefault();
        });
    });

    document.querySelectorAll('[data-copy]').forEach(function (button) {
        button.addEventListener('click', async function () {
            const note = document.querySelector('[data-copy-note]');
            try {
                await navigator.clipboard.writeText(button.dataset.copy);
                if (note) note.textContent = 'Link copied.';
            } catch (err) {
                if (note) note.textContent = button.dataset.copy;
            }
        });
    });
})();
