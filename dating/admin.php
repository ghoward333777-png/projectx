<?php

declare(strict_types=1);

require_once __DIR__ . '/SlowDatingEngine.php';
require_once __DIR__ . '/ui.php';

session_start();

$engine = new SlowDatingEngine();
$error = null;
$notice = null;
$adminId = null;

if (isset($_SESSION['sd_admin_token'])) {
    $auth = $engine->authenticate((string) $_SESSION['sd_admin_token']);
    if ($auth !== null && $auth[1] === 'admin') {
        $adminId = $auth[0];
    }
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    try {
        switch ((string) ($_POST['action'] ?? '')) {
            case 'bootstrap':
                $result = $engine->createAdmin((string) ($_POST['email'] ?? ''), (string) ($_POST['password'] ?? '') ?: null);
                $_SESSION['sd_admin_token'] = $result['token'];
                $adminId = $result['admin_id'];
                $notice = $result['auto_password'] !== null
                    ? 'Admin created. Generated password (shown once): ' . $result['auto_password']
                    : 'Admin created.';
                break;
            case 'login':
                $result = $engine->adminLogin((string) ($_POST['email'] ?? ''), (string) ($_POST['password'] ?? ''));
                $_SESSION['sd_admin_token'] = $result['token'];
                $adminId = $result['admin_id'];
                break;
            case 'logout':
                unset($_SESSION['sd_admin_token']);
                $adminId = null;
                break;
            case 'avatar_mode':
                if ($adminId !== null) {
                    $engine->setAvatarMode($adminId, (string) ($_POST['mode'] ?? ''));
                    $notice = 'Profile images now come from ' . ($engine->avatarMode() === 'uploads' ? 'member uploads (generated artwork as fallback).' : 'generated artwork for everyone.');
                }
                break;
            case 'watch_embed':
                if ($adminId !== null) {
                    $result = $engine->setWatchPartyEmbed($adminId, (string) ($_POST['embed'] ?? ''));
                    $notice = $result['watch_party_embed'] !== null
                        ? 'Watch Party player set. Every party now plays: ' . $result['watch_party_embed']
                        : 'Watch Party player cleared — parties play the film library again.';
                }
                break;
            case 'photo_reveal':
                if ($adminId !== null) {
                    $engine->setPhotoRevealDays($adminId, (int) ($_POST['days'] ?? 0));
                    $days = $engine->photoRevealDays();
                    $notice = $days === 0
                        ? 'Real pictures now reveal as soon as a chat starts. Premium members always see them immediately.'
                        : sprintf('Real pictures now reveal %d day%s after a pair\'s first chat. Premium members always see them immediately.', $days, $days === 1 ? '' : 's');
                }
                break;
            case 'review_verification':
                if ($adminId !== null) {
                    $result = $engine->reviewVerification($adminId, (string) ($_POST['user_id'] ?? ''), ($_POST['decision'] ?? '') === 'approve');
                    $notice = 'Verification ' . ($result['status'] === 'verified' ? 'approved — trust badge granted.' : 'rejected.');
                }
                break;
            case 'grant_rewards':
                if ($adminId !== null) {
                    $benefit = ['type' => (string) ($_POST['reward_type'] ?? '')];
                    $benefit['membership_tier'] = (string) ($_POST['membership_tier'] ?? 'member');
                    $benefit['amount'] = (float) ($_POST['amount'] ?? 0);
                    $benefit['product_id'] = (string) ($_POST['product_id'] ?? '');
                    $benefit['event_id'] = (string) ($_POST['event_id'] ?? '');
                    $benefit['quantity'] = (int) ($_POST['quantity'] ?? 2);
                    $benefit['description'] = (string) ($_POST['description'] ?? '');
                    $campaign = $engine->grantTopMemberRewards($adminId, (int) ($_POST['cohort'] ?? 0), $benefit);
                    $notice = sprintf(
                        'Campaign %s granted a %s to %d of the top %d members.',
                        $campaign['campaign_id'],
                        str_replace('_', ' ', $campaign['reward_type']),
                        $campaign['granted'],
                        $campaign['cohort'],
                    );
                }
                break;
        }
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
    }
}

sd_page_open('Admin Console', 'SlowDating · operations & rewards');
sd_flash($error, $notice);

if ($adminId === null) {
    $bootstrapped = $engine->store()->count('admins') > 0;
    ?>
    <div class="grid">
        <?php if (!$bootstrapped): ?>
            <form method="post">
                <h2>Bootstrap the first admin</h2>
                <input type="hidden" name="action" value="bootstrap">
                <label>Email</label><input name="email" type="email" required>
                <label>Password (blank = generated strong password)</label><input name="password" type="password">
                <button type="submit">Create admin</button>
            </form>
        <?php endif; ?>
        <form method="post">
            <h2>Admin sign in</h2>
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
?>
<section>
    <form method="post" style="background:none;border:0;padding:0;margin:0">
        <input type="hidden" name="action" value="logout"><button type="submit">Sign out</button>
    </form>
</section>

<form method="post">
    <h2>Profile images</h2>
    <p>Choose what member cards show across Browse, Matches, and Search.</p>
    <input type="hidden" name="action" value="avatar_mode">
    <?php $mode = $engine->avatarMode(); ?>
    <label style="display:flex;gap:10px;align-items:center;font-weight:400">
        <input type="radio" name="mode" value="generated" style="width:auto" <?= $mode === 'generated' ? 'checked' : '' ?>>
        Generated SVG artwork for everyone (no uploads shown)
    </label>
    <label style="display:flex;gap:10px;align-items:center;font-weight:400">
        <input type="radio" name="mode" value="uploads" style="width:auto" <?= $mode === 'uploads' ? 'checked' : '' ?>>
        Member-uploaded photos, with generated artwork as the fallback
    </label>
    <button type="submit">Save image mode</button>
</form>

<form method="post">
    <h2>Watch Party player</h2>
    <p>Paste YouTube embed code (the whole <code>&lt;iframe …&gt;</code>), a video link, or a playlist link.
        Every couple's Watch Party player will play it. Save an empty box to go back to the film library's own sources.</p>
    <input type="hidden" name="action" value="watch_embed">
    <label>Embed code or YouTube link</label>
    <textarea name="embed" placeholder='&lt;iframe src="https://www.youtube.com/embed/videoseries?list=PL..." ...&gt;&lt;/iframe&gt;'><?= sd_e((string) ($engine->watchPartyEmbed() ?? '')) ?></textarea>
    <button type="submit">Save player source</button>
</form>

<form method="post">
    <h2>Photo reveal timeframe</h2>
    <p>Relationships here start on common interests, not appearance. Real pictures stay behind the generated
        artwork until a pair's chat is this many days old — day 0 reveals at the first chat, day 1 after one
        day, and so on. Premium members hold the "Peek early" perk and see every member's pictures immediately.</p>
    <input type="hidden" name="action" value="photo_reveal">
    <label>Days after the first chat (0–<?= (int) SlowDatingEngine::PHOTO_REVEAL_MAX_DAYS ?>)</label>
    <input name="days" type="number" min="0" max="<?= (int) SlowDatingEngine::PHOTO_REVEAL_MAX_DAYS ?>" value="<?= (int) $engine->photoRevealDays() ?>">
    <button type="submit">Save reveal timeframe</button>
</form>

<form method="post">
    <h2>Grant free benefits to top members</h2>
    <p>Reward the most engaging members on the popularity leaderboard: free membership, gift certificates,
        products, event tickets, or all-expense-paid trips to company promotions.</p>
    <input type="hidden" name="action" value="grant_rewards">
    <div class="grid">
        <div>
            <label>Cohort</label>
            <select name="cohort">
                <?php foreach (SlowDatingEngine::REWARD_COHORTS as $cohort): ?>
                    <option value="<?= (int) $cohort ?>">Top <?= (int) $cohort ?></option>
                <?php endforeach; ?>
            </select>
        </div>
        <div>
            <label>Benefit</label>
            <select name="reward_type">
                <option value="free_membership">Free membership</option>
                <option value="gift_certificate">Gift certificate</option>
                <option value="product">Free product</option>
                <option value="event_tickets">Free event tickets</option>
                <option value="promo_trip">All-expense promo trip</option>
            </select>
        </div>
        <div>
            <label>Membership tier (free membership)</label>
            <select name="membership_tier">
                <?php foreach (array_keys(SlowDatingEngine::MEMBERSHIP_PRICES) as $tier): ?>
                    <option value="<?= sd_e($tier) ?>"><?= sd_e(ucfirst($tier)) ?></option>
                <?php endforeach; ?>
            </select>
        </div>
        <div><label>Amount $ (gift certificate)</label><input name="amount" type="number" step="0.01"></div>
        <div>
            <label>Product (free product)</label>
            <select name="product_id">
                <option value="">—</option>
                <?php foreach ($engine->products() as $product): ?>
                    <option value="<?= sd_e((string) $product['id']) ?>"><?= sd_e((string) $product['name']) ?></option>
                <?php endforeach; ?>
            </select>
        </div>
        <div>
            <label>Event (free tickets)</label>
            <select name="event_id">
                <option value="">—</option>
                <?php foreach ($engine->store()->all('events') as $event): ?>
                    <option value="<?= sd_e((string) $event['id']) ?>"><?= sd_e((string) $event['title']) ?></option>
                <?php endforeach; ?>
            </select>
        </div>
        <div><label>Ticket quantity</label><input name="quantity" type="number" value="2"></div>
    </div>
    <label>Trip description (promo trip)</label>
    <input name="description" placeholder="All-expense weekend at the spring launch gala">
    <button type="submit">Grant rewards</button>
</form>

<section>
    <h2>Verification queue</h2>
    <?php $pending = $engine->pendingVerifications(); ?>
    <?php if ($pending === []): ?>
        <p>No verification requests waiting.</p>
    <?php else: ?>
        <table>
            <tr><th>Member</th><th>Requested</th><th></th><th></th></tr>
            <?php foreach ($pending as $request): ?>
                <tr>
                    <td><?= sd_e((string) ($request['display_name'] ?: $request['user_id'])) ?></td>
                    <td><?= gmdate('M j, Y H:i', (int) $request['requested_at']) ?></td>
                    <td>
                        <form method="post" style="background:none;border:0;padding:0;margin:0">
                            <input type="hidden" name="action" value="review_verification">
                            <input type="hidden" name="user_id" value="<?= sd_e((string) $request['user_id']) ?>">
                            <input type="hidden" name="decision" value="approve">
                            <button type="submit" class="act small" style="margin:0">Approve</button>
                        </form>
                    </td>
                    <td>
                        <form method="post" style="background:none;border:0;padding:0;margin:0">
                            <input type="hidden" name="action" value="review_verification">
                            <input type="hidden" name="user_id" value="<?= sd_e((string) $request['user_id']) ?>">
                            <input type="hidden" name="decision" value="reject">
                            <button type="submit" style="margin:0;background:#3c1f32;color:#ff9cba;border:1px solid #7a3755;border-radius:999px;padding:6px 14px;font:inherit;font-weight:700;cursor:pointer">Reject</button>
                        </form>
                    </td>
                </tr>
            <?php endforeach; ?>
        </table>
    <?php endif; ?>
</section>

<section>
    <h2>Popularity leaderboard</h2>
    <table>
        <tr><th>#</th><th>Member</th><th>Score</th><th>Percentile</th><th>Raw engagement</th></tr>
        <?php foreach ($engine->topMembers(100) as $rank => $row): ?>
            <tr>
                <td><?= $rank + 1 ?></td>
                <td><?= sd_e((string) ($row['display_name'] ?: $row['user_id'])) ?></td>
                <td><?= (int) $row['popularity_score'] ?></td>
                <td>top <?= (int) $row['percentile'] ?>%</td>
                <td><?= (int) $row['raw_score'] ?></td>
            </tr>
        <?php endforeach; ?>
    </table>
</section>

<section>
    <h2>Recent reward grants</h2>
    <table>
        <tr><th>Member</th><th>Reward</th><th>Granted</th></tr>
        <?php
        $rewards = array_values($engine->store()->all('rewards'));
        usort($rewards, static fn (array $a, array $b): int => $b['granted_at'] <=> $a['granted_at']);
        foreach (array_slice($rewards, 0, 25) as $reward): ?>
            <tr>
                <td><?= sd_e((string) $reward['user_id']) ?></td>
                <td><?= sd_e(str_replace('_', ' ', (string) $reward['reward_type'])) ?></td>
                <td><?= gmdate('M j, Y H:i', (int) $reward['granted_at']) ?></td>
            </tr>
        <?php endforeach; ?>
    </table>
</section>

<?php sd_page_close(); ?>
