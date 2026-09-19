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
