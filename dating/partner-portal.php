<?php

declare(strict_types=1);

require_once __DIR__ . '/SlowDatingEngine.php';
require_once __DIR__ . '/ui.php';

session_start();

$engine = new SlowDatingEngine();
$error = null;
$notice = null;
$partnerId = null;

if (isset($_SESSION['sd_partner_token'])) {
    $auth = $engine->authenticate((string) $_SESSION['sd_partner_token']);
    if ($auth !== null && $auth[1] === 'partner') {
        $partnerId = $auth[0];
    }
}

$listField = static fn (string $name): array => array_values(array_filter(array_map(
    'trim',
    explode(',', (string) ($_POST[$name] ?? '')),
), static fn (string $v): bool => $v !== ''));

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    try {
        switch ((string) ($_POST['action'] ?? '')) {
            case 'signup':
                $result = $engine->signupPartner(
                    (string) ($_POST['business_name'] ?? ''),
                    (string) ($_POST['email'] ?? ''),
                    (string) ($_POST['password'] ?? '') ?: null,
                    (string) ($_POST['plan_tier'] ?? 'basic'),
                );
                $_SESSION['sd_partner_token'] = $result['token'];
                $partnerId = $result['partner_id'];
                $notice = $result['auto_password'] !== null
                    ? 'Partner account created. Your generated password (shown once): ' . $result['auto_password']
                    : 'Partner account created.';
                break;
            case 'login':
                $result = $engine->partnerLogin((string) ($_POST['email'] ?? ''), (string) ($_POST['password'] ?? ''));
                $_SESSION['sd_partner_token'] = $result['token'];
                $partnerId = $result['partner_id'];
                break;
            case 'logout':
                unset($_SESSION['sd_partner_token']);
                $partnerId = null;
                break;
            case 'create_venue':
                if ($partnerId !== null) {
                    $engine->createVenue($partnerId, [
                        'name' => $_POST['name'] ?? '',
                        'address' => $_POST['address'] ?? '',
                        'zip_code' => $_POST['zip_code'] ?? '',
                        'category' => $_POST['category'] ?? '',
                        'atmosphere_tags' => $listField('atmosphere_tags'),
                    ]);
                    $notice = 'Venue created.';
                }
                break;
            case 'random_coupon':
                if ($partnerId !== null) {
                    $coupon = $engine->createRandomCoupon($partnerId, (string) ($_POST['venue_id'] ?? ''), [
                        'discount_type' => $_POST['discount_type'] ?? 'percent',
                        'discount_amount' => (float) ($_POST['discount_amount'] ?? 0),
                        'max_recipients' => (int) ($_POST['max_recipients'] ?? 100),
                    ]);
                    $notice = 'Random coupon sent to ' . $coupon['estimated_reach'] . ' nearby members.';
                }
                break;
            case 'targeted_coupon':
                if ($partnerId !== null) {
                    $coupon = $engine->createTargetedCoupon($partnerId, (string) ($_POST['venue_id'] ?? ''), [
                        'discount_type' => $_POST['discount_type'] ?? 'percent',
                        'discount_amount' => (float) ($_POST['discount_amount'] ?? 0),
                        'max_recipients' => (int) ($_POST['max_recipients'] ?? 100),
                    ], [
                        'gender' => $_POST['gender'] ?? '',
                        'age_min' => ($_POST['age_min'] ?? '') !== '' ? (int) $_POST['age_min'] : null,
                        'age_max' => ($_POST['age_max'] ?? '') !== '' ? (int) $_POST['age_max'] : null,
                        'zip_radius_km' => (float) ($_POST['zip_radius_km'] ?? 40),
                        'interests' => $listField('interests'),
                    ]);
                    $notice = 'Targeted coupon reached ' . $coupon['estimated_reach'] . ' members in the segment.';
                }
                break;
            case 'create_event':
                if ($partnerId !== null) {
                    $engine->createEvent($partnerId, (string) ($_POST['venue_id'] ?? ''), [
                        'title' => $_POST['title'] ?? '',
                        'description' => $_POST['description'] ?? '',
                        'date_time' => strtotime((string) ($_POST['date_time'] ?? '')) ?: null,
                        'capacity' => (int) ($_POST['capacity'] ?? 50),
                        'ticket_price' => (float) ($_POST['ticket_price'] ?? 0),
                        'tags' => $listField('tags'),
                    ]);
                    $notice = 'Event announced to members.';
                }
                break;
            case 'create_contest':
                if ($partnerId !== null) {
                    $engine->createContest($partnerId, (string) ($_POST['venue_id'] ?? ''), [
                        'prize' => $_POST['prize'] ?? '',
                        'rules' => $_POST['rules'] ?? '',
                        'event_id' => $_POST['event_id'] ?? '',
                    ]);
                    $notice = 'Contest launched — every ticket buyer is entered automatically.';
                }
                break;
            case 'create_product':
                if ($partnerId !== null) {
                    $engine->createProduct($partnerId, (string) ($_POST['venue_id'] ?? ''), [
                        'name' => $_POST['name'] ?? '',
                        'description' => $_POST['description'] ?? '',
                        'category' => $_POST['category'] ?? 'gift',
                        'price' => (float) ($_POST['price'] ?? 0),
                        'inventory' => (int) ($_POST['inventory'] ?? 0),
                    ]);
                    $notice = 'Product listed in the member store.';
                }
                break;
            case 'create_meetup_ad':
                if ($partnerId !== null) {
                    $engine->createMeetupAd($partnerId, (string) ($_POST['venue_id'] ?? ''), [
                        'headline' => $_POST['headline'] ?? '',
                        'message' => $_POST['message'] ?? '',
                        'offer' => $_POST['offer'] ?? '',
                        'keys' => (array) ($_POST['keys'] ?? []),
                    ]);
                    $notice = 'Meet-up ad live. It flashes only when a couple starts arranging a date whose plans match your keys, near your town.';
                }
                break;
            case 'create_testimonial':
                if ($partnerId !== null) {
                    $engine->createTestimonialScript($partnerId, (string) ($_POST['venue_id'] ?? ''), [
                        'title' => $_POST['title'] ?? '',
                        'script' => $_POST['script'] ?? '',
                        'payout' => (float) ($_POST['payout'] ?? 0),
                    ]);
                    $notice = 'Testimonial offer published — popular members can now record it.';
                }
                break;
            case 'review_testimonial':
                if ($partnerId !== null) {
                    $reviewAction = (string) ($_POST['review'] ?? '');
                    $engine->reviewTestimonial($partnerId, (string) ($_POST['testimonial_id'] ?? ''), $reviewAction, [
                        'script' => $_POST['script'] ?? '',
                        'note' => $_POST['note'] ?? '',
                    ]);
                    $notice = match ($reviewAction) {
                        'accept' => 'Testimonial accepted — the member has been paid the offer\'s payout.',
                        'reject' => 'Testimonial rejected.',
                        'edit' => 'Script replaced — the member re-records to the edited script.',
                        'extend' => 'Script extended — the member records the addition.',
                        default => 'Review recorded.',
                    };
                }
                break;
            case 'change_plan':
                if ($partnerId !== null) {
                    $engine->changePartnerPlan($partnerId, (string) ($_POST['new_plan_tier'] ?? ''));
                    $notice = 'Plan changed.';
                }
                break;
        }
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
    }
}

sd_page_open('Partner Portal', 'SlowMoDating.com · partner control center');
sd_flash($error, $notice);

if ($partnerId === null) {
    ?>
    <p>Restaurants, lounges, cruise lines, tour and experience companies, bodyguard services, and vendors:
        reach serious daters with coupons, singles events, contests, and store products.</p>
    <div class="grid">
        <form method="post">
            <h2>Partner signup</h2>
            <input type="hidden" name="action" value="signup">
            <label>Business name</label><input name="business_name" required>
            <label>Contact email</label><input name="email" type="email" required>
            <label>Password (blank = generated)</label><input name="password" type="password">
            <label>Plan</label>
            <select name="plan_tier">
                <option value="basic">Basic — free listing, random coupons, events</option>
                <option value="pro">Pro — targeted coupons, contests, analytics</option>
                <option value="elite">Elite — priority concierge placement, deep analytics</option>
            </select>
            <button type="submit">Create partner account</button>
        </form>
        <form method="post">
            <h2>Partner sign in</h2>
            <input type="hidden" name="action" value="login">
            <label>Email</label><input name="email" type="email" required>
            <label>Password</label><input name="password" type="password" required>
            <button type="submit">Sign in</button>
        </form>
    </div>
    <?php
    sd_page_close();
    exit;
}

$partner = $engine->partner($partnerId);
$venues = $engine->venuesForPartner($partnerId);
?>
<section>
    <h2><?= sd_e((string) $partner['business_name']) ?></h2>
    <p>Plan: <span class="pill"><?= sd_e((string) $partner['plan_tier']) ?></span></p>
    <div class="grid">
        <form method="post" class="card" style="margin-top:0">
            <input type="hidden" name="action" value="change_plan">
            <label>Change plan</label>
            <select name="new_plan_tier">
                <?php foreach (SlowDatingEngine::PARTNER_TIERS as $tier): ?>
                    <option value="<?= sd_e($tier) ?>"<?= $partner['plan_tier'] === $tier ? ' selected' : '' ?>><?= sd_e(ucfirst($tier)) ?></option>
                <?php endforeach; ?>
            </select>
            <button type="submit">Update plan</button>
        </form>
        <form method="post" class="card" style="margin-top:0"><input type="hidden" name="action" value="logout"><button type="submit">Sign out</button></form>
    </div>
</section>

<form method="post">
    <h2>Add a venue</h2>
    <input type="hidden" name="action" value="create_venue">
    <div class="grid">
        <div><label>Name</label><input name="name" required></div>
        <div><label>Zip code</label><input name="zip_code" required></div>
        <div><label>Category</label>
            <select name="category">
                <?php foreach (SlowDatingEngine::VENUE_CATEGORIES as $category): ?>
                    <option value="<?= sd_e($category) ?>"><?= sd_e($category) ?></option>
                <?php endforeach; ?>
            </select>
        </div>
        <div><label>Address</label><input name="address"></div>
    </div>
    <label>Atmosphere tags (comma separated: quiet, romantic, jazz, dance_friendly, no_kids, game_night, outdoor)</label>
    <input name="atmosphere_tags" placeholder="quiet, romantic">
    <button type="submit">Create venue</button>
</form>

<?php foreach ($venues as $venue):
    $venueId = (string) $venue['id'];
    $analytics = $engine->venueAnalytics($venueId);
    ?>
    <section>
        <h2><?= sd_e((string) $venue['name']) ?> <span class="pill"><?= sd_e((string) $venue['category']) ?></span></h2>
        <p><?php foreach ((array) $venue['atmosphere_tags'] as $tag): ?><span class="pill"><?= sd_e((string) $tag) ?></span><?php endforeach; ?></p>
        <div class="grid">
            <div class="metric card"><strong><?= (int) $analytics['total_coupons_created'] ?></strong><span>coupons</span></div>
            <div class="metric card"><strong><?= (int) $analytics['total_redemptions'] ?></strong><span>redemptions</span></div>
            <div class="metric card"><strong><?= (int) $analytics['total_tickets_sold'] ?></strong><span>tickets sold</span></div>
            <div class="metric card"><strong>$<?= number_format((float) $analytics['ticket_revenue'], 2) ?></strong><span>ticket revenue</span></div>
            <div class="metric card"><strong><?= (int) $analytics['total_contest_entries'] ?></strong><span>contest entries</span></div>
            <div class="metric card"><strong><?= (int) $analytics['meetup_ad_impressions'] ?></strong><span>meet-up ad flashes</span></div>
        </div>

        <div class="grid">
            <form method="post" class="card" style="margin-top:14px">
                <h2>Random coupon</h2>
                <input type="hidden" name="action" value="random_coupon">
                <input type="hidden" name="venue_id" value="<?= sd_e($venueId) ?>">
                <label>Discount</label><input name="discount_amount" type="number" step="0.01" required>
                <label>Type</label><select name="discount_type"><option value="percent">percent</option><option value="fixed">fixed $</option></select>
                <label>Max recipients</label><input name="max_recipients" type="number" value="100">
                <button type="submit">Send to nearby members</button>
            </form>

            <form method="post" class="card" style="margin-top:14px">
                <h2>Targeted coupon (Pro/Elite)</h2>
                <input type="hidden" name="action" value="targeted_coupon">
                <input type="hidden" name="venue_id" value="<?= sd_e($venueId) ?>">
                <label>Discount</label><input name="discount_amount" type="number" step="0.01" required>
                <label>Type</label><select name="discount_type"><option value="percent">percent</option><option value="fixed">fixed $</option></select>
                <label>Gender</label><input name="gender" placeholder="female / male / blank for all">
                <label>Age range</label>
                <div class="grid"><input name="age_min" type="number" placeholder="18"><input name="age_max" type="number" placeholder="30"></div>
                <label>Zip radius (km)</label><input name="zip_radius_km" type="number" value="20">
                <label>Interests</label><input name="interests" placeholder="jazz, wine">
                <label>Max recipients</label><input name="max_recipients" type="number" value="100">
                <button type="submit">Send targeted coupon</button>
            </form>

            <form method="post" class="card" style="margin-top:14px">
                <h2>Announce singles event</h2>
                <input type="hidden" name="action" value="create_event">
                <input type="hidden" name="venue_id" value="<?= sd_e($venueId) ?>">
                <label>Title</label><input name="title" required>
                <label>Date/time</label><input name="date_time" type="datetime-local">
                <label>Capacity</label><input name="capacity" type="number" value="50">
                <label>Ticket price ($)</label><input name="ticket_price" type="number" step="0.01" value="0">
                <label>Tags</label><input name="tags" placeholder="singles, quiet, dance">
                <label>Description</label><textarea name="description"></textarea>
                <button type="submit">Announce event</button>
            </form>

            <form method="post" class="card" style="margin-top:14px">
                <h2>Launch contest (Pro/Elite)</h2>
                <input type="hidden" name="action" value="create_contest">
                <input type="hidden" name="venue_id" value="<?= sd_e($venueId) ?>">
                <label>Prize</label><input name="prize" required>
                <label>Tie to event (optional)</label>
                <select name="event_id">
                    <option value="">Any ticket at this venue</option>
                    <?php foreach ($engine->eventsForVenue($venueId) as $event): ?>
                        <option value="<?= sd_e((string) $event['id']) ?>"><?= sd_e((string) $event['title']) ?></option>
                    <?php endforeach; ?>
                </select>
                <label>Rules</label><textarea name="rules"></textarea>
                <button type="submit">Launch contest</button>
            </form>

            <form method="post" class="card" style="margin-top:14px">
                <h2>Meet-up ad + keys (Pro/Elite)</h2>
                <p style="margin:4px 0;font-size:12.5px;color:#a294ad">Your second ad. It flashes the moment a couple
                    starts arranging a real date whose plans match your keys, in your town. You never learn who or where —
                    only how many times it showed.</p>
                <input type="hidden" name="action" value="create_meetup_ad">
                <input type="hidden" name="venue_id" value="<?= sd_e($venueId) ?>">
                <label>Headline</label><input name="headline" placeholder="Date night at <?= sd_e((string) $venue['name']) ?>?" required>
                <label>Message</label><textarea name="message" placeholder="Quiet corner tables, perfect before a movie."></textarea>
                <label>Offer (optional)</label><input name="offer" placeholder="Show this ad for a free dessert">
                <label>Keys — the date-talk that triggers your ad</label>
                <?php foreach (SlowDatingEngine::AD_KEYS as $key => $patterns): ?>
                    <label style="display:flex;gap:8px;align-items:center;font-weight:400;margin:2px 0">
                        <input type="checkbox" name="keys[]" value="<?= sd_e($key) ?>" style="width:auto">
                        <?= sd_e(ucwords(str_replace('_', ' ', $key))) ?>
                        <span style="color:#a294ad;font-size:11.5px">(<?= sd_e(implode(', ', array_slice($patterns, 0, 3))) ?>…)</span>
                    </label>
                <?php endforeach; ?>
                <button type="submit">Buy keys &amp; launch ad</button>
            </form>

            <form method="post" class="card" style="margin-top:14px">
                <h2>Testimonial offer</h2>
                <p style="margin:4px 0;font-size:12.5px;color:#a294ad">Script a testimonial and set the payout.
                    Popular members record it; you accept (they are paid), reject, edit the script for a
                    re-record, or extend it.</p>
                <input type="hidden" name="action" value="create_testimonial">
                <input type="hidden" name="venue_id" value="<?= sd_e($venueId) ?>">
                <label>Title</label><input name="title" placeholder="30-second date-night testimonial" required>
                <label>Script the member reads</label><textarea name="script" required></textarea>
                <label>Payout on acceptance ($)</label><input name="payout" type="number" step="0.01" min="0.01" required>
                <button type="submit">Publish testimonial offer</button>
            </form>

            <form method="post" class="card" style="margin-top:14px">
                <h2>List a store product</h2>
                <input type="hidden" name="action" value="create_product">
                <input type="hidden" name="venue_id" value="<?= sd_e($venueId) ?>">
                <label>Name</label><input name="name" required>
                <label>Price ($)</label><input name="price" type="number" step="0.01" required>
                <label>Inventory</label><input name="inventory" type="number" value="10">
                <label>Category</label><input name="category" value="gift">
                <label>Description</label><textarea name="description"></textarea>
                <button type="submit">List product</button>
            </form>
        </div>

        <?php $coupons = $engine->couponsForVenue($venueId); ?>
        <?php if ($coupons !== []): ?>
            <h2 style="margin-top:16px">Coupons</h2>
            <table>
                <tr><th>Type</th><th>Discount</th><th>Reach</th><th>Valid to</th></tr>
                <?php foreach ($coupons as $coupon): ?>
                    <tr>
                        <td><?= sd_e((string) $coupon['type']) ?></td>
                        <td><?= $coupon['discount_type'] === 'percent' ? (int) $coupon['discount_amount'] . '%' : '$' . number_format((float) $coupon['discount_amount'], 2) ?></td>
                        <td><?= count((array) $coupon['recipients']) ?> members</td>
                        <td><?= gmdate('M j, Y', (int) $coupon['valid_to']) ?></td>
                    </tr>
                <?php endforeach; ?>
            </table>
        <?php endif; ?>

        <?php $submissions = $engine->testimonialsForVenue($venueId); ?>
        <?php if ($submissions !== []): ?>
            <h2 style="margin-top:16px">Testimonial submissions</h2>
            <div class="grid">
                <?php foreach ($submissions as $submission): ?>
                    <div class="card">
                        <strong><?= sd_e((string) $submission['video_url']) ?></strong>
                        <span class="pill"><?= sd_e((string) $submission['status']) ?></span>
                        <span class="pill">$<?= number_format((float) $submission['payout'], 2) ?></span>
                        <?php if ((string) $submission['notes'] !== ''): ?><p style="margin:6px 0"><?= sd_e((string) $submission['notes']) ?></p><?php endif; ?>
                        <p style="margin:6px 0;white-space:pre-line;font-size:13px;color:#c9bfd2"><?= sd_e((string) $submission['script_text']) ?></p>
                        <form method="post" style="background:none;border:0;padding:0;margin:0">
                            <input type="hidden" name="action" value="review_testimonial">
                            <input type="hidden" name="testimonial_id" value="<?= sd_e((string) $submission['id']) ?>">
                            <label>Decision</label>
                            <select name="review">
                                <option value="accept">Accept — pay the member</option>
                                <option value="reject">Reject</option>
                                <option value="edit">Edit — replace the script</option>
                                <option value="extend">Extend — add to the script</option>
                            </select>
                            <label>New / added script (for edit or extend)</label>
                            <textarea name="script"></textarea>
                            <label>Note to the member (optional)</label>
                            <input name="note">
                            <button type="submit">Send review</button>
                        </form>
                    </div>
                <?php endforeach; ?>
            </div>
        <?php endif; ?>

        <?php $contests = $engine->contestsForVenue($venueId); ?>
        <?php if ($contests !== []): ?>
            <h2 style="margin-top:16px">Contests</h2>
            <table>
                <tr><th>Prize</th><th>Entries</th><th>Ends</th></tr>
                <?php foreach ($contests as $contest): ?>
                    <tr>
                        <td><?= sd_e((string) $contest['prize']) ?></td>
                        <td><?= (int) $engine->contestEntries((string) $contest['id'])['entries_count'] ?></td>
                        <td><?= gmdate('M j, Y', (int) $contest['end_date']) ?></td>
                    </tr>
                <?php endforeach; ?>
            </table>
        <?php endif; ?>
    </section>
<?php endforeach; ?>

<?php sd_page_close(); ?>
