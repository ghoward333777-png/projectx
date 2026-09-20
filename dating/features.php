<?php

declare(strict_types=1);

require_once __DIR__ . '/ui.php';

/**
 * Features — the public feature list, grouped by audience. Content is a
 * plain data array so the list stays easy to keep in step with
 * FEATURE_SPEC.md when the platform grows.
 */

$groups = [
    ['For members', [
        ['Slow chat that earns real time', 'Messages start at 5 a day and 280 characters, widen every week, and unlock into unlimited real-time chat after 30 days and 10 genuine two-way conversations.'],
        ['Contact-info protection', 'Phone numbers, emails, links, and social handles are erased from messages until a chat unlocks — contact sharing is earned, never rushed.'],
        ['11-factor matching', 'Distance, interests, hobbies, outdoor life, dating goal, faith, politics, income, occupation, automobile, and popularity balance blend into one match score.'],
        ['Deep search', 'Filter the community by zip proximity, age, interests, hobbies, outdoor activities, dating type, faith, politics, income range, automobile, occupation, and popularity.'],
        ['Popularity rating', 'A fair 0–100 score from the attention you receive, normalized within your own group. Others see the score — never who viewed or messaged you.'],
        ['Video profiles', 'Embed up to five YouTube videos, validated and rendered safely.'],
        ['AI date concierge', 'Reads what a chat is really about and suggests up to three vetted nearby venues, each with a plain-language reason.'],
        ['Coupons, events & store', 'Partner discounts land in your wallet, event tickets enter you in venue contests automatically, and the store sells date-night kits with live stock.'],
        ['Member rewards', 'The most engaging members receive free memberships, gift certificates, tickets, and sponsored trips — visible in your wallet.'],
        ['Honest membership', 'Free to join. Member $19/year, VIP $79 (early chat unlock, boost), Elite $199 (chaperone priority, elite events).'],
        ['Daily drop', 'Three people picked for you each day from your saved preferences — fewer, better matches instead of endless swiping.'],
        ['Profile prompts', 'Answer up to three personality prompts; they become the ice breakers your matches see.'],
        ['AI co-pilot', 'A profile coach with a strength score and concrete next steps, ice-breaker suggestions per chat, and a conversation-health read on every conversation.'],
        ['Niche communities', 'Creatives, tech founders, spiritual, single parents, LGBTQ+, fitness, travelers, entrepreneurs — each with its own member grid.'],
    ]],
    ['Safety, women first', [
        ['Filtering before trust', 'Contact data cannot leave a chat before the 30-day unlock — the scammer\'s rush tactic simply doesn\'t work here.'],
        ['Red-flag detection', 'Money requests, urgency pressure, off-platform pushes, and coercion raise an automatic safety alert for the recipient.'],
        ['Safety education', 'A public Safety Center with red flags, a first-date checklist, and exit strategies.'],
        ['Vetted venues only', 'Every recommended venue is atmosphere-tagged: quiet, romantic, adult, date-compatible.'],
        ['VIP chaperones', 'Professional bodyguard partners offer discreet escorts, safe-arrival verification, and emergency response for any date.'],
        ['Strong passwords, always', 'A twelve-character four-class minimum for every account, with a generated strong password offered at signup.'],
        ['Verification & trust badges', 'Members request verification, admins review, and verified profiles carry a ✓ badge on every card across the site.'],
    ]],
    ['For partner businesses', [
        ['Self-service portal', 'Restaurants, lounges, cruise lines, tour and experience companies, bodyguard services, and vendors sign up and manage everything themselves.'],
        ['Three plans', 'Basic (free listing, random coupons, events), Pro (targeted coupons, contests, analytics), Elite (priority concierge placement, deep reporting).'],
        ['Precision coupons', 'Random offers to nearby members, or targeted segments like "women 21–35 within 30 km" — with estimated reach before you send.'],
        ['Events & contests', 'Announce singles nights with capacity-controlled ticketing; attach prize draws that enter every ticket buyer automatically.'],
        ['A shelf in the store', 'List date-night products with live inventory; the platform handles orders.'],
        ['Live analytics', 'Coupons sent, redemptions, tickets sold, revenue, and contest entries — computed from the actual records.'],
        ['System integration', 'External ticketing, reservation, and booking systems report in over signed webhooks.'],
    ]],
    ['The platform', [
        ['Runs anywhere', 'Dependency-free PHP 8.1+ — no database server, no packages, no API keys. Deploys to any shared host by copying one folder.'],
        ['Full API', 'Every feature is available over a JSON API with a complete OpenAPI contract.'],
        ['Deterministic & tested', 'Same inputs always produce the same results, and an automated contract suite verifies every rule before anything ships.'],
        ['Desktop & mobile', 'One responsive interface across phones, tablets, and desktops.'],
    ]],
];

sd_page_open('Features', 'SlowDating · everything the platform does');
?>
<p style="max-width:70ch">Every capability of the platform at a glance — what members get, how safety is
    built in, what partner businesses can do, and what the technology guarantees. The full rules behind each
    item live in the technical specification.</p>

<?php foreach ($groups as [$heading, $features]): ?>
    <section>
        <h2><?= sd_e($heading) ?></h2>
        <div class="grid">
            <?php foreach ($features as [$name, $blurb]): ?>
                <div class="card">
                    <strong><?= sd_e($name) ?></strong>
                    <span style="color:#c4b8ce;font-size:13.5px;line-height:1.55"><?= sd_e($blurb) ?></span>
                </div>
            <?php endforeach; ?>
        </div>
    </section>
<?php endforeach; ?>

<section>
    <h2>See it for yourself</h2>
    <p><a href="site-tour.php">Take the one-minute Site Tour</a> · <a href="index.php">Create a free account</a> · <a href="partner-portal.php">Become a partner</a></p>
</section>

<?php sd_page_close(); ?>
