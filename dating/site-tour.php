<?php

declare(strict_types=1);

require_once __DIR__ . '/ui.php';

/**
 * Site Tour — a public slideshow walking through every page of SlowDating.
 * Slides are real captures of the app running with demo data; regenerate
 * them by re-running the capture flow after UI changes (see README).
 */

$slides = [
    ['01-home.jpg', 'Welcome to SlowDating', 'Free to join with a $19/year membership. Contact details stay filtered until a chat has lived 30 days with 10 real conversations — then it opens to real time.'],
    ['02-matches.jpg', 'Your matches', 'Ranked by an 11-factor compatibility score: distance, interests, hobbies, dating type, faith, politics, income, occupation, automobile, outdoor life, and popularity balance.'],
    ['03-slow-chat.jpg', 'Slow chat that earns real time', 'Message size and frequency start limited and widen weekly. Phone numbers, emails, links, and handles are erased before storage until the chat unlocks — watch the filter catch a shared number.'],
    ['04-search.jpg', 'Search on what matters to you', 'Filter members by zip proximity, age, interests, hobbies, dating type, faith, politics, income range, automobile, occupation, and popularity.'],
    ['05-profile.jpg', 'A profile with depth', 'Everything searchable lives on the profile — plus embedded YouTube videos and a popularity breakdown only you can see.'],
    ['06-wallet.jpg', 'Coupons, rewards, and events', 'Partner venues send you real offers, the operations team rewards the most engaging members, and every event ticket can enter you in a venue contest.'],
    ['07-store.jpg', 'The date-night store', 'Curated kits and gifts from partner venues, with live inventory.'],
    ['08-membership.jpg', 'Simple, honest membership', 'Member at $19/year, VIP with early chat unlock at $79, Elite with chaperone priority at $199. Ads and partners fund the rest.'],
    ['09-partner.jpg', 'A portal for partners', 'Restaurants, lounges, cruise lines, and experience providers run coupons, singles events, contests, and store products — with live analytics.'],
    ['10-safety.jpg', 'Safety first, women first', 'Contact filtering, red-flag detection, vetted venues, safety education, and VIP chaperone services — protection is the product, not an add-on.'],
    ['11-smart-dating.jpg', 'Smart Dating: the science of choosing well', 'Nine short articles on why intense attraction misleads, the neuroscience underneath it, and why slow-built relationships hold — the research the whole platform is designed around.'],
];

sd_page_open('Site Tour', 'SlowDating · see every page in one minute');
?>
<style>
    .tour { background: #1d1824; border: 1px solid #3d3346; border-radius: 16px; padding: 18px; }
    .stage { position: relative; background: #14101b; border-radius: 12px; overflow: hidden; }
    .stage img { display: block; width: 100%; height: auto; }
    .slide { display: none; }
    .slide.on { display: block; }
    .arrow { position: absolute; top: 50%; transform: translateY(-50%); border: 0; cursor: pointer;
             background: rgba(19, 16, 24, .72); color: #ffc4da; font-size: 26px; line-height: 1;
             width: 44px; height: 44px; border-radius: 999px; }
    .arrow:hover { background: rgba(58, 42, 62, .9); }
    .arrow.prev { left: 10px; }
    .arrow.next { right: 10px; }
    .caption { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 12px; margin-top: 12px; }
    .caption strong { font-size: 18px; }
    .caption .n { color: #a294ad; font-size: 13px; font-variant-numeric: tabular-nums; }
    .caption p { flex-basis: 100%; margin: 0; }
    .dots { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; align-items: center; }
    .dots button { width: 11px; height: 11px; border-radius: 999px; border: 0; cursor: pointer; background: #3a2a3e; padding: 0; }
    .dots button.on { background: #ff9cc0; }
    .dots .play { width: auto; height: auto; background: #262030; border: 1px solid #3d3346; color: #ffc4da;
                  border-radius: 999px; padding: 5px 13px; font: inherit; font-weight: 700; margin-left: auto; }
</style>

<p>One minute, every page: how slow chat protects you, how matching works, and what partners bring to your dates.
    Use the arrows, the dots, or your keyboard's ← → keys.</p>

<div class="tour">
    <div class="stage" id="stage">
        <?php foreach ($slides as $i => [$file, $title, $caption]): ?>
            <div class="slide<?= $i === 0 ? ' on' : '' ?>">
                <img src="assets/tour/<?= sd_e($file) ?>" alt="<?= sd_e($title) ?>" <?= $i === 0 ? '' : 'loading="lazy"' ?>>
            </div>
        <?php endforeach; ?>
        <button type="button" class="arrow prev" id="prev" aria-label="Previous slide">&#8249;</button>
        <button type="button" class="arrow next" id="next" aria-label="Next slide">&#8250;</button>
    </div>
    <div class="caption">
        <strong id="cap-title"></strong>
        <span class="n"><span id="cap-num">1</span> / <?= count($slides) ?></span>
        <p id="cap-text"></p>
    </div>
    <div class="dots" id="dots">
        <?php foreach ($slides as $i => $slide): ?>
            <button type="button" data-go="<?= $i ?>" aria-label="Slide <?= $i + 1 ?>"></button>
        <?php endforeach; ?>
        <button type="button" class="play" id="play">Pause</button>
    </div>
</div>

<section>
    <h2 style="margin-top:0">Ready to try it?</h2>
    <p><a href="index.php">Create a free account</a> · <a href="partner-portal.php">Become a partner venue</a> · <a href="safety-center.php">Read the safety guide</a></p>
</section>

<script>
    (function () {
        var slides = <?= json_encode(array_map(static fn (array $s): array => [$s[1], $s[2]], $slides)) ?>;
        var at = 0, playing = true, timer = null;
        var els = document.querySelectorAll('.slide');
        var dots = document.querySelectorAll('#dots button[data-go]');
        function show(i) {
            at = (i + slides.length) % slides.length;
            for (var k = 0; k < els.length; k++) { els[k].classList.toggle('on', k === at); dots[k].classList.toggle('on', k === at); }
            document.getElementById('cap-title').textContent = slides[at][0];
            document.getElementById('cap-text').textContent = slides[at][1];
            document.getElementById('cap-num').textContent = at + 1;
        }
        function arm() { clearInterval(timer); if (playing) { timer = setInterval(function () { show(at + 1); }, 6000); } }
        document.getElementById('prev').addEventListener('click', function () { show(at - 1); arm(); });
        document.getElementById('next').addEventListener('click', function () { show(at + 1); arm(); });
        document.getElementById('dots').addEventListener('click', function (e) {
            var b = e.target.closest('button[data-go]'); if (b) { show(+b.dataset.go); arm(); }
        });
        document.getElementById('play').addEventListener('click', function () {
            playing = !playing; this.textContent = playing ? 'Pause' : 'Play'; arm();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'ArrowLeft') { show(at - 1); arm(); }
            if (e.key === 'ArrowRight') { show(at + 1); arm(); }
        });
        if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            playing = false; document.getElementById('play').textContent = 'Play';
        }
        show(0); arm();
    })();
</script>

<?php sd_page_close(); ?>
