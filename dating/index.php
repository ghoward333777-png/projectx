<?php

declare(strict_types=1);

require_once __DIR__ . '/SlowDatingEngine.php';
require_once __DIR__ . '/ui.php';

session_start();

$engine = new SlowDatingEngine();
$error = null;
$notice = null;
$userId = null;

if (isset($_SESSION['sd_member_token'])) {
    $auth = $engine->authenticate((string) $_SESSION['sd_member_token']);
    if ($auth !== null && $auth[1] === 'member') {
        $userId = $auth[0];
    }
}

$action = (string) ($_POST['action'] ?? '');
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    try {
        switch ($action) {
            case 'signup':
                $result = $engine->signupMember(
                    (string) ($_POST['email'] ?? ''),
                    (string) ($_POST['password'] ?? '') ?: null,
                    ($_POST['password'] ?? '') === '',
                );
                $_SESSION['sd_member_token'] = $result['token'];
                $userId = $result['user_id'];
                $notice = $result['password_generated']
                    ? 'Welcome! Your generated password (store it now, it is shown once): ' . $result['auto_password']
                    : 'Welcome to SlowDating!';
                break;
            case 'login':
                $result = $engine->login((string) ($_POST['email'] ?? ''), (string) ($_POST['password'] ?? ''));
                $_SESSION['sd_member_token'] = $result['token'];
                $userId = $result['user_id'];
                break;
            case 'logout':
                unset($_SESSION['sd_member_token']);
                $userId = null;
                break;
            case 'profile':
                if ($userId !== null) {
                    $engine->updateProfile($userId, $_POST);
                    $notice = 'Profile saved.';
                }
                break;
            case 'add_video':
                if ($userId !== null) {
                    $engine->addProfileVideo($userId, (string) ($_POST['youtube_url'] ?? ''));
                    $notice = 'Video added to your profile.';
                }
                break;
            case 'start_chat':
                if ($userId !== null) {
                    $engine->startChat($userId, (string) ($_POST['user_id'] ?? ''));
                    $notice = 'Chat started — slow-chat pacing applies for the first 30 days.';
                }
                break;
            case 'send_message':
                if ($userId !== null) {
                    $sent = $engine->sendMessage((string) ($_POST['chat_id'] ?? ''), $userId, (string) ($_POST['text'] ?? ''));
                    if ((int) $sent['contact_data_removed'] > 0) {
                        $notice = 'Message sent. Personal contact data was removed — contact sharing opens after 30 days and 10 real conversations.';
                    }
                }
                break;
            case 'redeem_coupon':
                if ($userId !== null) {
                    $engine->redeemCoupon((string) ($_POST['coupon_id'] ?? ''), $userId);
                    $notice = 'Coupon redeemed — show this screen at the venue.';
                }
                break;
            case 'buy_ticket':
                if ($userId !== null) {
                    $engine->buyTicket((string) ($_POST['event_id'] ?? ''), $userId, (int) ($_POST['quantity'] ?? 1));
                    $notice = 'Tickets purchased. If the venue runs a contest, you are entered automatically.';
                }
                break;
            case 'order_product':
                if ($userId !== null) {
                    $engine->placeOrder($userId, (string) ($_POST['product_id'] ?? ''), (int) ($_POST['quantity'] ?? 1));
                    $notice = 'Order placed.';
                }
                break;
            case 'subscribe':
                if ($userId !== null) {
                    $plan = $engine->subscribeMembership($userId, (string) ($_POST['tier'] ?? 'member'));
                    $notice = sprintf('You are now a %s member ($%.2f/year).', $plan['membership_tier'], $plan['price']);
                }
                break;
        }
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
    }
}

sd_page_open('SlowDating', 'SlowDating · take your time, meet for real');
sd_flash($error, $notice);

if ($userId === null) {
    ?>
    <p>Slow-paced chat that speeds up as trust builds. Contact details stay filtered until a chat has lived
        <strong>30 days with 10 real conversations</strong> — then it opens to real time. Free to join, $19/year membership,
        real-world dates at vetted partner venues.</p>
    <div class="grid">
        <form method="post">
            <h2>Create account</h2>
            <input type="hidden" name="action" value="signup">
            <label for="su-email">Email</label>
            <input id="su-email" name="email" type="email" required>
            <label for="su-pass">Password (leave blank for a generated strong password)</label>
            <input id="su-pass" name="password" type="password" minlength="12" placeholder="12+ chars, upper/lower/digit/symbol">
            <button type="submit">Join SlowDating</button>
        </form>
        <form method="post">
            <h2>Sign in</h2>
            <input type="hidden" name="action" value="login">
            <label for="li-email">Email</label>
            <input id="li-email" name="email" type="email" required>
            <label for="li-pass">Password</label>
            <input id="li-pass" name="password" type="password" required>
            <button type="submit">Sign in</button>
        </form>
    </div>
    <?php
    sd_page_close();
    exit;
}

$profile = $engine->profile($userId);
$popularity = $engine->popularity($userId);
$tab = (string) ($_GET['tab'] ?? 'matches');
$tabs = ['matches' => 'Matches', 'search' => 'Search', 'chats' => 'Chats', 'profile' => 'My profile', 'wallet' => 'Coupons & rewards', 'store' => 'Store', 'membership' => 'Membership'];
?>
<section>
    <div class="grid">
        <div class="metric card"><strong><?= (int) $popularity['popularity_score'] ?></strong><span>Popularity (0–100) · top <?= (int) $popularity['percentile'] ?>% · <?= sd_e((string) $popularity['trend']) ?></span></div>
        <div class="metric card"><strong><?= sd_e((string) ($profile['display_name'] ?: $userId)) ?></strong><span><?= sd_e($userId) ?> · <?= sd_e((string) $engine->store()->get('users', $userId)['membership_tier']) ?> member</span></div>
        <form method="post" class="card" style="margin-top:0"><input type="hidden" name="action" value="logout"><button type="submit">Sign out</button></form>
    </div>
    <p class="links">
        <?php foreach ($tabs as $key => $label): ?>
            <a href="?tab=<?= sd_e($key) ?>"<?= $tab === $key ? ' style="font-weight:800;text-decoration:underline"' : '' ?>><?= sd_e($label) ?></a>
        <?php endforeach; ?>
    </p>
</section>

<?php if ($tab === 'profile'): ?>
    <form method="post">
        <h2>My profile</h2>
        <input type="hidden" name="action" value="profile">
        <div class="grid">
            <div><label>Display name</label><input name="display_name" value="<?= sd_e((string) $profile['display_name']) ?>"></div>
            <div><label>Age</label><input name="age" type="number" min="18" value="<?= (int) $profile['age'] ?: '' ?>"></div>
            <div><label>Gender</label><input name="gender" value="<?= sd_e((string) $profile['gender']) ?>"></div>
            <div><label>Zip code</label><input name="zip_code" value="<?= sd_e((string) $profile['zip_code']) ?>"></div>
            <div><label>Dating type</label>
                <select name="dating_type">
                    <option value="">—</option>
                    <?php foreach (SlowDatingEngine::DATING_TYPES as $type): ?>
                        <option value="<?= sd_e($type) ?>"<?= $profile['dating_type'] === $type ? ' selected' : '' ?>><?= sd_e($type) ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div><label>Faith</label><input name="faith" value="<?= sd_e((string) $profile['faith']) ?>"></div>
            <div><label>Politics</label><input name="politics" value="<?= sd_e((string) $profile['politics']) ?>"></div>
            <div><label>Income range</label>
                <select name="income_range">
                    <option value="">—</option>
                    <?php foreach (SlowDatingEngine::INCOME_RANGES as $range): ?>
                        <option value="<?= sd_e($range) ?>"<?= $profile['income_range'] === $range ? ' selected' : '' ?>><?= sd_e($range) ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div><label>Automobile</label>
                <select name="automobile">
                    <option value="">—</option>
                    <?php foreach (SlowDatingEngine::AUTOMOBILES as $auto): ?>
                        <option value="<?= sd_e($auto) ?>"<?= $profile['automobile'] === $auto ? ' selected' : '' ?>><?= sd_e($auto) ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div><label>Occupation category</label><input name="occupation_category" value="<?= sd_e((string) $profile['occupation_category']) ?>"></div>
        </div>
        <label>Interests (comma separated)</label><input name="interests" value="<?= sd_e(implode(', ', (array) $profile['interests'])) ?>">
        <label>Hobbies</label><input name="hobbies" value="<?= sd_e(implode(', ', (array) $profile['hobbies'])) ?>">
        <label>Outdoor activities</label><input name="outdoor_activities" value="<?= sd_e(implode(', ', (array) $profile['outdoor_activities'])) ?>">
        <button type="submit">Save profile</button>
    </form>
    <section>
        <h2>Profile videos</h2>
        <?php foreach ((array) $profile['videos'] as $video): ?>
            <div class="card" style="margin-bottom:10px">
                <iframe width="100%" height="220" src="<?= sd_e((string) $video['embed_url']) ?>" title="Profile video" frameborder="0" allowfullscreen></iframe>
            </div>
        <?php endforeach; ?>
        <form method="post" style="margin-top:0">
            <input type="hidden" name="action" value="add_video">
            <label>YouTube URL (clips of 10 seconds or less)</label><input name="youtube_url" placeholder="https://www.youtube.com/watch?v=...">
            <button type="submit">Embed video</button>
        </form>
    </section>
    <section>
        <h2>My popularity breakdown (only you can see this)</h2>
        <?php $breakdown = $engine->popularityBreakdown($userId); ?>
        <div class="grid">
            <?php foreach ($breakdown['metrics'] as $metric => $count): ?>
                <div class="metric card"><strong><?= (int) $count ?></strong><span><?= sd_e(str_replace('_', ' ', (string) $metric)) ?></span></div>
            <?php endforeach; ?>
        </div>
    </section>

<?php elseif ($tab === 'search'): ?>
    <form method="get">
        <h2>Search members</h2>
        <input type="hidden" name="tab" value="search">
        <div class="grid">
            <div><label>Zip code</label><input name="zip_code" value="<?= sd_e((string) ($_GET['zip_code'] ?? '')) ?>"></div>
            <div><label>Radius (km)</label><input name="zip_radius_km" type="number" value="<?= sd_e((string) ($_GET['zip_radius_km'] ?? '')) ?>"></div>
            <div><label>Gender</label><input name="gender" value="<?= sd_e((string) ($_GET['gender'] ?? '')) ?>"></div>
            <div><label>Age min</label><input name="age_min" type="number" value="<?= sd_e((string) ($_GET['age_min'] ?? '')) ?>"></div>
            <div><label>Age max</label><input name="age_max" type="number" value="<?= sd_e((string) ($_GET['age_max'] ?? '')) ?>"></div>
            <div><label>Interests</label><input name="interests" value="<?= sd_e((string) ($_GET['interests'] ?? '')) ?>"></div>
            <div><label>Hobbies</label><input name="hobbies" value="<?= sd_e((string) ($_GET['hobbies'] ?? '')) ?>"></div>
            <div><label>Dating type</label><input name="dating_type" value="<?= sd_e((string) ($_GET['dating_type'] ?? '')) ?>"></div>
            <div><label>Faith</label><input name="faith" value="<?= sd_e((string) ($_GET['faith'] ?? '')) ?>"></div>
            <div><label>Politics</label><input name="politics" value="<?= sd_e((string) ($_GET['politics'] ?? '')) ?>"></div>
            <div><label>Income range</label><input name="income_range" value="<?= sd_e((string) ($_GET['income_range'] ?? '')) ?>"></div>
            <div><label>Automobile</label><input name="automobile" value="<?= sd_e((string) ($_GET['automobile'] ?? '')) ?>"></div>
            <div><label>Occupation</label><input name="occupation_category" value="<?= sd_e((string) ($_GET['occupation_category'] ?? '')) ?>"></div>
            <div><label>Min popularity</label><input name="min_popularity" type="number" value="<?= sd_e((string) ($_GET['min_popularity'] ?? '')) ?>"></div>
        </div>
        <button type="submit">Search</button>
    </form>
    <section>
        <h2>Results</h2>
        <?php
        $filters = array_filter($_GET, static fn ($value): bool => $value !== '' && $value !== null);
        unset($filters['tab']);
        foreach ($engine->searchUsers($filters) as $row):
            if ($row['user_id'] === $userId) {
                continue;
            }
            ?>
            <div class="card" style="margin-bottom:10px">
                <div class="who" style="margin-bottom:6px">
                    <img class="avatar" src="avatar.php?u=<?= urlencode((string) $row['user_id']) ?>" alt="">
                    <strong><?= sd_e((string) ($row['display_name'] ?: $row['user_id'])) ?></strong>
                </div>
                popularity <?= (int) $row['popularity_score'] ?> (top <?= (int) $row['percentile'] ?>%)
                <?php if (isset($row['zip_distance_km'])): ?> · ~<?= sd_e((string) $row['zip_distance_km']) ?> km<?php endif; ?><br>
                <?php foreach ((array) $row['interests'] as $interest): ?><span class="pill"><?= sd_e((string) $interest) ?></span><?php endforeach; ?>
                <form method="post" style="background:none;border:0;padding:0;margin:0">
                    <input type="hidden" name="action" value="start_chat">
                    <input type="hidden" name="user_id" value="<?= sd_e((string) $row['user_id']) ?>">
                    <button type="submit">Start slow chat</button>
                </form>
            </div>
        <?php endforeach; ?>
    </section>

<?php elseif ($tab === 'chats'): ?>
    <?php foreach ($engine->chatsFor($userId) as $chat):
        $chatId = (string) $chat['id'];
        $status = $engine->chatStatus($chatId);
        $other = '';
        foreach ((array) $chat['participants'] as $participant) {
            if ($participant !== $userId) {
                $other = (string) $participant;
            }
        }
        $otherProfile = $engine->profile($other);
        ?>
        <section>
            <h2>Chat with <?= sd_e((string) ($otherProfile['display_name'] ?: $other)) ?></h2>
            <p>
                <?php if ($status['unlocked']): ?>
                    <span class="pill">Real-time · contact sharing open</span>
                <?php else: ?>
                    <span class="pill">Slow chat · day <?= (int) $status['age_days'] ?>/<?= (int) $status['days_required'] ?></span>
                    <span class="pill">Conversations <?= (int) $status['completed_sessions'] ?>/<?= (int) $status['sessions_required'] ?></span>
                    <span class="pill"><?= (int) $status['daily_message_limit'] ?> msgs/day · <?= (int) $status['message_size_limit'] ?> chars</span>
                    <span class="pill">Contact info filtered</span>
                <?php endif; ?>
            </p>
            <div class="chat-log">
                <?php foreach ((array) $chat['messages'] as $message): ?>
                    <div class="msg <?= $message['sender_id'] === $userId ? 'mine' : 'theirs' ?>">
                        <?= sd_e((string) $message['text']) ?>
                        <small><?= gmdate('M j H:i', (int) $message['sent_at']) ?><?= ((int) $message['contact_data_removed']) > 0 ? ' · contact info removed' : '' ?></small>
                    </div>
                <?php endforeach; ?>
            </div>
            <form method="post" style="margin-top:10px">
                <input type="hidden" name="action" value="send_message">
                <input type="hidden" name="chat_id" value="<?= sd_e($chatId) ?>">
                <label>Message<?= $status['unlocked'] ? '' : ' (max ' . (int) $status['message_size_limit'] . ' characters)' ?></label>
                <textarea name="text" <?= $status['unlocked'] ? '' : 'maxlength="' . (int) $status['message_size_limit'] . '"' ?>></textarea>
                <button type="submit">Send</button>
            </form>
            <?php $suggestions = $engine->conciergeSuggestions($chatId); ?>
            <?php if ($suggestions !== []): ?>
                <h2 style="margin-top:16px">Date concierge suggestions</h2>
                <div class="grid">
                    <?php foreach ($suggestions as $suggestion): ?>
                        <div class="card">
                            <strong><?= sd_e((string) $suggestion['venue_name']) ?></strong> (<?= sd_e((string) $suggestion['category']) ?>)<br>
                            <?php foreach ((array) $suggestion['atmosphere_tags'] as $tag): ?><span class="pill"><?= sd_e((string) $tag) ?></span><?php endforeach; ?>
                            <p><?= sd_e((string) $suggestion['reason']) ?></p>
                        </div>
                    <?php endforeach; ?>
                </div>
            <?php endif; ?>
        </section>
    <?php endforeach; ?>
    <?php if ($engine->chatsFor($userId) === []): ?>
        <section><p>No chats yet — find someone in <a href="?tab=search">Search</a> or <a href="?tab=matches">Matches</a>.</p></section>
    <?php endif; ?>

<?php elseif ($tab === 'wallet'): ?>
    <section>
        <h2>My coupons</h2>
        <?php foreach ($engine->couponsForMember($userId) as $coupon):
            $venue = $engine->store()->get('venues', (string) $coupon['venue_id']);
            ?>
            <div class="card" style="margin-bottom:10px">
                <strong><?= sd_e((string) ($venue['name'] ?? 'Partner venue')) ?></strong> —
                <?= $coupon['discount_type'] === 'percent' ? (int) $coupon['discount_amount'] . '% off' : '$' . number_format((float) $coupon['discount_amount'], 2) . ' off' ?>
                · valid until <?= gmdate('M j, Y', (int) $coupon['valid_to']) ?>
                <form method="post" style="background:none;border:0;padding:0;margin:0">
                    <input type="hidden" name="action" value="redeem_coupon">
                    <input type="hidden" name="coupon_id" value="<?= sd_e((string) $coupon['id']) ?>">
                    <button type="submit">Redeem</button>
                </form>
            </div>
        <?php endforeach; ?>
    </section>
    <section>
        <h2>My rewards</h2>
        <?php foreach ($engine->rewardsFor($userId) as $reward): ?>
            <div class="card" style="margin-bottom:10px">
                <strong><?= sd_e(str_replace('_', ' ', (string) $reward['reward_type'])) ?></strong>
                · granted <?= gmdate('M j, Y', (int) $reward['granted_at']) ?>
                <?php if (isset($reward['detail']['description'])): ?><p><?= sd_e((string) $reward['detail']['description']) ?></p><?php endif; ?>
                <?php if (isset($reward['detail']['amount'])): ?><p>Gift certificate value: $<?= number_format((float) $reward['detail']['amount'], 2) ?></p><?php endif; ?>
            </div>
        <?php endforeach; ?>
    </section>
    <section>
        <h2>Upcoming partner events</h2>
        <?php foreach ($engine->store()->all('events') as $event):
            $venue = $engine->store()->get('venues', (string) $event['venue_id']);
            ?>
            <div class="card" style="margin-bottom:10px">
                <strong><?= sd_e((string) $event['title']) ?></strong> at <?= sd_e((string) ($venue['name'] ?? '')) ?>
                · <?= gmdate('M j, Y H:i', (int) $event['date_time']) ?> · $<?= number_format((float) $event['ticket_price'], 2) ?>
                <form method="post" style="background:none;border:0;padding:0;margin:0">
                    <input type="hidden" name="action" value="buy_ticket">
                    <input type="hidden" name="event_id" value="<?= sd_e((string) $event['id']) ?>">
                    <button type="submit">Buy ticket</button>
                </form>
            </div>
        <?php endforeach; ?>
    </section>

<?php elseif ($tab === 'store'): ?>
    <section>
        <h2>Date-night store</h2>
        <div class="grid">
            <?php foreach ($engine->products() as $product): ?>
                <div class="card">
                    <strong><?= sd_e((string) $product['name']) ?></strong><br>
                    $<?= number_format((float) $product['price'], 2) ?> · <?= (int) $product['inventory'] ?> left
                    <p><?= sd_e((string) $product['description']) ?></p>
                    <form method="post" style="background:none;border:0;padding:0;margin:0">
                        <input type="hidden" name="action" value="order_product">
                        <input type="hidden" name="product_id" value="<?= sd_e((string) $product['id']) ?>">
                        <button type="submit">Buy</button>
                    </form>
                </div>
            <?php endforeach; ?>
        </div>
    </section>

<?php elseif ($tab === 'membership'): ?>
    <section>
        <h2>Membership</h2>
        <p>Free accounts browse and slow-chat. Paid membership funds a bot-free community and unlocks the full experience.</p>
        <div class="grid">
            <?php foreach (SlowDatingEngine::MEMBERSHIP_PRICES as $tier => $price): ?>
                <form method="post" class="card" style="margin-top:0">
                    <input type="hidden" name="action" value="subscribe">
                    <input type="hidden" name="tier" value="<?= sd_e($tier) ?>">
                    <strong><?= sd_e(ucfirst($tier)) ?></strong> — $<?= number_format($price, 2) ?>/year
                    <p><?= $tier === 'member' ? 'Full membership: matches, coupons, events, store.' : ($tier === 'vip' ? 'Everything in Member plus early chat unlock and profile boost.' : 'Everything in VIP plus chaperone booking priority and elite events.') ?></p>
                    <button type="submit">Choose <?= sd_e($tier) ?></button>
                </form>
            <?php endforeach; ?>
        </div>
    </section>

<?php else: ?>
    <section>
        <h2>Your matches</h2>
        <?php foreach ($engine->matchesFor($userId, ['limit' => 10]) as $match): ?>
            <div class="card" style="margin-bottom:10px">
                <div class="who" style="margin-bottom:6px">
                    <img class="avatar" src="avatar.php?u=<?= urlencode((string) $match['user_id']) ?>" alt="">
                    <strong><?= sd_e((string) ($match['display_name'] ?: $match['user_id'])) ?></strong>
                </div>
                match score <?= (int) $match['match_score'] ?> · popularity <?= (int) $match['popularity_score'] ?>
                · ~<?= sd_e((string) $match['zip_distance_km']) ?> km<br>
                <?php foreach ((array) $match['shared_interests'] as $interest): ?><span class="pill">both: <?= sd_e((string) $interest) ?></span><?php endforeach; ?>
                <form method="post" style="background:none;border:0;padding:0;margin:0">
                    <input type="hidden" name="action" value="start_chat">
                    <input type="hidden" name="user_id" value="<?= sd_e((string) $match['user_id']) ?>">
                    <button type="submit">Start slow chat</button>
                </form>
            </div>
        <?php endforeach; ?>
    </section>
<?php endif; ?>

<?php sd_page_close(); ?>
