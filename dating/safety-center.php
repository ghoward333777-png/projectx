<?php

declare(strict_types=1);

require_once __DIR__ . '/SlowDatingEngine.php';
require_once __DIR__ . '/ui.php';

$engine = new SlowDatingEngine();
$resources = $engine->safetyResources();

sd_page_open('Safety Center', 'SlowMoDating.com · women-first safety education');
?>
<p>SlowMoDating is built safety-first: contact details stay filtered out of chat until a conversation has
    proven itself over 30 days, red-flag behaviour raises alerts automatically, every partner venue is vetted
    for a quiet, adult, date-compatible atmosphere, and VIP chaperone services can be booked for any date.</p>

<section>
    <h2>Red flags to watch for</h2>
    <ul>
        <?php foreach ($resources['red_flags'] as $item): ?>
            <li><?= sd_e($item) ?></li>
        <?php endforeach; ?>
    </ul>
</section>

<section>
    <h2>First-date checklist</h2>
    <ul>
        <?php foreach ($resources['first_date_checklist'] as $item): ?>
            <li><?= sd_e($item) ?></li>
        <?php endforeach; ?>
    </ul>
</section>

<section>
    <h2>Exit strategies</h2>
    <ul>
        <?php foreach ($resources['exit_strategies'] as $item): ?>
            <li><?= sd_e($item) ?></li>
        <?php endforeach; ?>
    </ul>
</section>

<section>
    <h2>How the platform protects you</h2>
    <ul>
        <li><strong>Contact data filtering:</strong> phone numbers, emails, links, and social handles are erased from messages until a chat unlocks (30 days + 10 real conversations).</li>
        <li><strong>Slow-chat pacing:</strong> limited message size and frequency early on defeats the rapid-pressure playbook scammers rely on.</li>
        <li><strong>Red-flag detection:</strong> money requests, urgency pressure, and off-platform pushes raise a safety event on your account automatically.</li>
        <li><strong>Vetted venues only:</strong> partner venues are tagged for quiet, adult atmospheres — no high-noise, child-heavy, or unvetted locations.</li>
        <li><strong>VIP chaperones:</strong> professional bodyguard partners offer discreet escorts, safe-arrival verification, and emergency response.</li>
        <li><strong>Privacy-first popularity:</strong> other members only ever see your normalized rating — never raw counts of who messaged or viewed you.</li>
    </ul>
</section>

<?php sd_page_close(); ?>
