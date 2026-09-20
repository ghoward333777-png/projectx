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
            case 'upload_photo':
                if ($userId !== null) {
                    $upload = $_FILES['photo'] ?? null;
                    if (!is_array($upload) || ($upload['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK) {
                        throw new InvalidArgumentException('Choose a JPEG, PNG, or WebP photo up to 2 MB.');
                    }
                    $slot = (string) ($_POST['slot'] ?? 'public');
                    $engine->setMemberPhoto($userId, (string) file_get_contents((string) $upload['tmp_name']), (string) $upload['type'], $slot);
                    $notice = $slot === 'private'
                        ? 'Private picture saved. It is shown only in chats where you choose it.'
                        : 'Real picture saved.';
                }
                break;
            case 'share_image':
                if ($userId !== null) {
                    $upload = $_FILES['image'] ?? null;
                    if (!is_array($upload) || ($upload['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK) {
                        throw new InvalidArgumentException('Choose a JPEG, PNG, or WebP image up to 2 MB.');
                    }
                    $engine->sendImageMessage(
                        (string) ($_POST['chat_id'] ?? ''),
                        $userId,
                        (string) file_get_contents((string) $upload['tmp_name']),
                        (string) $upload['type'],
                        (string) ($_POST['caption'] ?? ''),
                    );
                    $notice = 'Image shared — only the two of you can see it.';
                }
                break;
            case 'chat_image':
                if ($userId !== null) {
                    $result = $engine->setChatImageChoice((string) ($_POST['chat_id'] ?? ''), $userId, (string) ($_POST['choice'] ?? ''));
                    $notice = 'They now see your ' . ['generated' => 'artwork', 'public' => 'real picture', 'private' => 'private picture'][$result['image_choice']] . ' in this chat.';
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
            case 'request_verification':
                if ($userId !== null) {
                    $engine->requestVerification($userId);
                    $notice = 'Verification requested — an admin will review it. Verified profiles carry a trust badge everywhere.';
                }
                break;
            case 'save_prompts':
                if ($userId !== null) {
                    $answers = [];
                    for ($i = 0; $i < 3; $i++) {
                        $id = (string) ($_POST['prompt_id_' . $i] ?? '');
                        $text = trim((string) ($_POST['prompt_text_' . $i] ?? ''));
                        if ($id !== '' && $text !== '') {
                            $answers[] = ['id' => $id, 'text' => $text];
                        }
                    }
                    $engine->setPrompts($userId, $answers);
                    $notice = 'Prompts saved — they feed your matches\' ice breakers.';
                }
                break;
            case 'join_community':
                if ($userId !== null) {
                    $engine->joinCommunity($userId, (string) ($_POST['slug'] ?? ''));
                    $notice = 'Welcome to the community.';
                }
                break;
            case 'leave_community':
                if ($userId !== null) {
                    $engine->leaveCommunity($userId, (string) ($_POST['slug'] ?? ''));
                    $notice = 'Left the community.';
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
$tabs = ['matches' => 'Matches', 'search' => 'Search', 'chats' => 'Chats', 'communities' => 'Communities', 'profile' => 'My profile', 'wallet' => 'Coupons & rewards', 'store' => 'Store', 'membership' => 'Membership'];
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
            <div><label>Family plans</label>
                <select name="family_plans">
                    <option value="">—</option>
                    <?php foreach (SlowDatingEngine::FAMILY_PLANS as $option): ?>
                        <option value="<?= sd_e($option) ?>"<?= ($profile['family_plans'] ?? '') === $option ? ' selected' : '' ?>><?= sd_e(ucwords(str_replace('_', ' ', $option))) ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div><label>Smoking</label>
                <select name="smoking">
                    <option value="">—</option>
                    <?php foreach (SlowDatingEngine::SMOKING as $option): ?>
                        <option value="<?= sd_e($option) ?>"<?= ($profile['smoking'] ?? '') === $option ? ' selected' : '' ?>><?= sd_e(ucfirst($option)) ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div><label>Drinking</label>
                <select name="drinking">
                    <option value="">—</option>
                    <?php foreach (SlowDatingEngine::DRINKING as $option): ?>
                        <option value="<?= sd_e($option) ?>"<?= ($profile['drinking'] ?? '') === $option ? ' selected' : '' ?>><?= sd_e(ucfirst($option)) ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div><label>Pets</label>
                <select name="pets">
                    <option value="">—</option>
                    <?php foreach (SlowDatingEngine::PETS as $option): ?>
                        <option value="<?= sd_e($option) ?>"<?= ($profile['pets'] ?? '') === $option ? ' selected' : '' ?>><?= sd_e(ucfirst($option)) ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
            <div><label>Education</label>
                <select name="education">
                    <option value="">—</option>
                    <?php foreach (SlowDatingEngine::EDUCATION_LEVELS as $level): ?>
                        <option value="<?= sd_e($level) ?>"<?= ($profile['education'] ?? '') === $level ? ' selected' : '' ?>><?= sd_e(ucwords(str_replace('_', ' ', $level))) ?></option>
                    <?php endforeach; ?>
                </select>
            </div>
        </div>
        <label>Interests (comma separated)</label><input name="interests" value="<?= sd_e(implode(', ', (array) $profile['interests'])) ?>">
        <label>Hobbies</label><input name="hobbies" value="<?= sd_e(implode(', ', (array) $profile['hobbies'])) ?>">
        <label>Outdoor activities</label><input name="outdoor_activities" value="<?= sd_e(implode(', ', (array) $profile['outdoor_activities'])) ?>">
        <button type="submit">Save profile</button>
    </form>
    <section>
        <h2>Your three profile pictures</h2>
        <?php $roster = $engine->pictureRoster($userId); ?>
        <p>Every profile carries three pictures: your <strong style="color:#f3eef6">artwork</strong> (always there),
            your <strong style="color:#f3eef6">real picture</strong>, and a <strong style="color:#f3eef6">private picture</strong>
            shown only in chats where you choose it. When you connect with someone, you pick which one they see.
            <?= $roster['complete'] ? '' : 'Your profile is missing ' . (!$roster['public'] && !$roster['private'] ? 'your real and private pictures.' : (!$roster['public'] ? 'your real picture.' : 'your private picture.')) ?></p>
        <div class="grid">
            <div class="card">
                <strong>1 · Artwork</strong>
                <img class="avatar" style="width:96px;height:96px" src="avatar.php?u=<?= urlencode($userId) ?>&art=1" alt="Generated artwork">
                <span style="color:#a294ad;font-size:12.5px">Generated for you — always available.</span>
            </div>
            <div class="card">
                <strong>2 · Real picture <?= $roster['public'] ? '' : '· missing' ?></strong>
                <?php if ($roster['public']): ?><img class="avatar" style="width:96px;height:96px" src="photo.php?slot=public&t=<?= time() ?>" alt="Your real picture"><?php endif; ?>
                <form method="post" enctype="multipart/form-data" style="background:none;border:0;padding:0;margin:0">
                    <input type="hidden" name="action" value="upload_photo">
                    <input type="hidden" name="slot" value="public">
                    <input type="file" name="photo" accept="image/jpeg,image/png,image/webp" required>
                    <button type="submit" class="act small" style="margin-top:8px">Save real picture</button>
                </form>
            </div>
            <div class="card">
                <strong>3 · Private picture <?= $roster['private'] ? '' : '· missing' ?></strong>
                <?php if ($roster['private']): ?><img class="avatar" style="width:96px;height:96px" src="photo.php?slot=private&t=<?= time() ?>" alt="Your private picture"><?php endif; ?>
                <form method="post" enctype="multipart/form-data" style="background:none;border:0;padding:0;margin:0">
                    <input type="hidden" name="action" value="upload_photo">
                    <input type="hidden" name="slot" value="private">
                    <input type="file" name="photo" accept="image/jpeg,image/png,image/webp" required>
                    <button type="submit" class="act small" style="margin-top:8px">Save private picture</button>
                </form>
                <span style="color:#a294ad;font-size:12.5px">Never shown on Browse or Search — only in chats where you reveal it.</span>
            </div>
        </div>
    </section>
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
        <h2>Profile coach</h2>
        <?php $coach = $engine->profileCoach($userId); ?>
        <div class="grid">
            <div class="metric card"><strong><?= (int) $coach['score'] ?></strong><span>profile strength (0–100)</span></div>
            <div class="card" style="grid-column:span 2">
                <?php if ($coach['suggestions'] === []): ?>
                    <span>Your profile is at full strength — nothing to improve.</span>
                <?php else: ?>
                    <strong>Raise your score:</strong>
                    <ul style="margin:6px 0 0;padding-left:18px;color:#c4b8ce">
                        <?php foreach ($coach['suggestions'] as $suggestion): ?>
                            <li><?= sd_e($suggestion) ?></li>
                        <?php endforeach; ?>
                    </ul>
                <?php endif; ?>
            </div>
        </div>
    </section>
    <section>
        <h2>Verification</h2>
        <?php $verification = $engine->verificationStatus($userId); ?>
        <?php if ($verification === 'verified'): ?>
            <p><span class="pill ok">✓ verified</span> Your trust badge shows on every card.</p>
        <?php elseif ($verification === 'pending'): ?>
            <p><span class="pill">pending review</span> An admin is reviewing your request.</p>
        <?php else: ?>
            <p>Verified profiles carry a trust badge on Browse, Matches, Search, and Communities.</p>
            <form method="post" style="background:none;border:0;padding:0;margin:0">
                <input type="hidden" name="action" value="request_verification">
                <button type="submit" class="act small">Request verification</button>
            </form>
        <?php endif; ?>
    </section>
    <form method="post">
        <h2>Your prompts</h2>
        <p style="margin-top:0">Answer up to three — they appear as ice breakers for people you connect with.</p>
        <input type="hidden" name="action" value="save_prompts">
        <?php $myPrompts = $engine->prompts($userId); ?>
        <?php for ($i = 0; $i < 3; $i++): $current = $myPrompts[$i] ?? null; ?>
            <div class="grid" style="grid-template-columns:1fr 1.4fr;margin-bottom:8px">
                <select name="prompt_id_<?= $i ?>">
                    <option value="">— pick a prompt —</option>
                    <?php foreach (SlowDatingEngine::PROMPTS as $pid => $question): ?>
                        <option value="<?= sd_e($pid) ?>"<?= ($current['id'] ?? '') === $pid ? ' selected' : '' ?>><?= sd_e($question) ?></option>
                    <?php endforeach; ?>
                </select>
                <input name="prompt_text_<?= $i ?>" maxlength="200" value="<?= sd_e((string) ($current['answer'] ?? '')) ?>" placeholder="Your answer (200 chars max)">
            </div>
        <?php endfor; ?>
        <button type="submit">Save prompts</button>
    </form>
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
            <div><label>Education</label><input name="education" value="<?= sd_e((string) ($_GET['education'] ?? '')) ?>" placeholder="bachelors, masters…"></div>
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
                    <?= !empty($row['verified']) ? '<span class="pill ok">✓ verified</span>' : '' ?>
                    <?= ($row['dating_type'] ?? '') !== '' ? '<span class="pill">' . sd_e(str_replace('_', ' ', (string) $row['dating_type'])) . '</span>' : '' ?>
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
        <?php
        $myChoice = $engine->chatImageChoice($chatId, $userId);
        $myRoster = $engine->pictureRoster($userId);
        $chosen = isset($chat['image_choices'][$userId]);
        ?>
        <section>
            <div class="who" style="margin-bottom:6px">
                <img class="avatar" src="avatar.php?u=<?= urlencode($other) ?>&amp;chat=<?= urlencode($chatId) ?>" alt="">
                <h2 style="margin:0">Chat with <?= sd_e((string) ($otherProfile['display_name'] ?: $other)) ?></h2>
            </div>
            <?php if (!$chosen): ?>
                <div class="notice" style="margin:0 0 10px">You're connected — which of your three profile pictures should
                    <?= sd_e((string) ($otherProfile['display_name'] ?: 'they')) ?> see? Until you choose, they see your artwork.</div>
            <?php endif; ?>
            <form method="post" style="background:none;border:0;padding:0;margin:0 0 10px">
                <input type="hidden" name="action" value="chat_image">
                <input type="hidden" name="chat_id" value="<?= sd_e($chatId) ?>">
                <label style="margin-top:0">Picture they see from you</label>
                <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr));align-items:center">
                    <select name="choice">
                        <option value="generated"<?= $myChoice === 'generated' ? ' selected' : '' ?>>My artwork</option>
                        <option value="public"<?= $myChoice === 'public' ? ' selected' : '' ?><?= $myRoster['public'] ? '' : ' disabled' ?>>My real picture<?= $myRoster['public'] ? '' : ' (upload it first)' ?></option>
                        <option value="private"<?= $myChoice === 'private' ? ' selected' : '' ?><?= $myRoster['private'] ? '' : ' disabled' ?>>My private picture<?= $myRoster['private'] ? '' : ' (upload it first)' ?></option>
                    </select>
                    <button type="submit" class="act small" style="margin-top:0">Save</button>
                </div>
            </form>
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
                        <?php if (isset($message['image'])): ?>
                            <img src="chatimage.php?chat=<?= urlencode($chatId) ?>&amp;m=<?= urlencode((string) $message['message_id']) ?>"
                                 alt="Shared image" style="display:block;max-width:220px;border-radius:10px;margin-bottom:<?= $message['text'] !== '' ? '6px' : '0' ?>">
                        <?php endif; ?>
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
            <form method="post" enctype="multipart/form-data" style="margin-top:10px">
                <input type="hidden" name="action" value="share_image">
                <input type="hidden" name="chat_id" value="<?= sd_e($chatId) ?>">
                <label>Share an image (JPEG, PNG, or WebP · max 2 MB · visible only to the two of you<?= $status['unlocked'] ? '' : ' · counts toward today\'s messages' ?>)</label>
                <div class="grid" style="grid-template-columns:1fr 1fr auto;align-items:center;gap:10px">
                    <input type="file" name="image" accept="image/jpeg,image/png,image/webp" required>
                    <input name="caption" placeholder="Optional caption">
                    <button type="submit" class="act small" style="margin-top:0">Share</button>
                </div>
            </form>
            <?php $health = $engine->conversationHealth($chatId); ?>
            <p style="margin:10px 0 4px"><span class="pill<?= $health['score'] >= 45 ? ' ok' : '' ?>">conversation health: <?= (int) $health['score'] ?> · <?= sd_e((string) $health['label']) ?></span>
                <span style="color:#a294ad;font-size:12.5px"><?= sd_e((string) $health['notes'][0]) ?></span></p>
            <?php $breakers = $engine->iceBreakers($chatId, $userId); ?>
            <?php if ((array) $chat['messages'] === [] || count((array) $chat['messages']) < 4): ?>
                <div class="card" style="margin-top:8px">
                    <strong>Ice breakers</strong>
                    <ul style="margin:4px 0 0;padding-left:18px;color:#c4b8ce">
                        <?php foreach ($breakers as $breaker): ?>
                            <li><?= sd_e($breaker) ?></li>
                        <?php endforeach; ?>
                    </ul>
                </div>
            <?php endif; ?>
            <?php $meetupAds = $engine->meetupAdsForChat($chatId); ?>
            <?php if ($meetupAds !== []): ?>
                <div class="grid" style="margin-top:10px">
                    <?php foreach ($meetupAds as $ad): ?>
                        <div class="card" style="border:1px solid #574a61">
                            <span style="color:#a294ad;font-size:11px;letter-spacing:.1em;text-transform:uppercase">Sponsored · you're planning a date</span>
                            <strong><?= sd_e((string) $ad['headline']) ?></strong>
                            <span style="color:#c4b8ce;font-size:13px"><?= sd_e((string) $ad['message']) ?></span>
                            <?php if ($ad['offer'] !== ''): ?><span class="pill ok"><?= sd_e((string) $ad['offer']) ?></span><?php endif; ?>
                            <span style="color:#a294ad;font-size:12px"><?= sd_e((string) $ad['venue_name']) ?> · ~<?= sd_e((string) $ad['distance_km']) ?> km from you</span>
                        </div>
                    <?php endforeach; ?>
                </div>
            <?php endif; ?>
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

<?php elseif ($tab === 'communities'): ?>
    <?php
    $mine = $engine->memberCommunities($userId);
    $viewing = (string) ($_GET['community'] ?? '');
    ?>
    <section>
        <h2>Niche communities</h2>
        <p>Join the circles that describe you — each has its own member grid, and specificity makes better matches.</p>
        <div class="cards" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px">
            <?php foreach (SlowDatingEngine::COMMUNITIES as $slug => $label):
                $joined = in_array($slug, $mine, true); ?>
                <div class="card">
                    <strong><a href="?tab=communities&amp;community=<?= sd_e($slug) ?>" style="color:#f3eef6;text-decoration:none"><?= sd_e($label) ?></a></strong>
                    <span style="color:#a294ad;font-size:12.5px"><?= count($engine->communityMembers($slug)) ?> member<?= count($engine->communityMembers($slug)) === 1 ? '' : 's' ?><?= $joined ? ' · you are in' : '' ?></span>
                    <form method="post" style="background:none;border:0;padding:0;margin:0">
                        <input type="hidden" name="action" value="<?= $joined ? 'leave_community' : 'join_community' ?>">
                        <input type="hidden" name="slug" value="<?= sd_e($slug) ?>">
                        <button type="submit" class="<?= $joined ? 'quiet' : 'act small' ?>" style="margin-top:6px"><?= $joined ? 'Leave' : 'Join' ?></button>
                    </form>
                </div>
            <?php endforeach; ?>
        </div>
    </section>
    <?php if ($viewing !== '' && isset(SlowDatingEngine::COMMUNITIES[$viewing])): ?>
        <section>
            <h2><?= sd_e(SlowDatingEngine::COMMUNITIES[$viewing]) ?> — member grid</h2>
            <div class="cards" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px">
                <?php foreach ($engine->communityMembers($viewing) as $member):
                    if ($member['user_id'] === $userId) {
                        continue;
                    } ?>
                    <div class="card">
                        <div class="who">
                            <img class="avatar" src="avatar.php?u=<?= urlencode((string) $member['user_id']) ?>" alt="">
                            <div>
                                <strong><?= sd_e((string) ($member['display_name'] ?: $member['user_id'])) ?><?= $member['age'] ? ', ' . (int) $member['age'] : '' ?></strong>
                                <?= $member['verified'] ? '<span class="pill ok">✓ verified</span>' : '' ?><br>
                                <span style="color:#a294ad;font-size:12.5px">popularity <?= (int) $member['popularity_score'] ?><?= $member['dating_type'] !== '' ? ' · ' . sd_e(str_replace('_', ' ', (string) $member['dating_type'])) : '' ?></span>
                            </div>
                        </div>
                        <form method="post" style="background:none;border:0;padding:0;margin:6px 0 0">
                            <input type="hidden" name="action" value="start_chat">
                            <input type="hidden" name="user_id" value="<?= sd_e((string) $member['user_id']) ?>">
                            <button type="submit" class="act small">Start slow chat</button>
                        </form>
                    </div>
                <?php endforeach; ?>
            </div>
        </section>
    <?php endif; ?>

<?php else: ?>
    <section>
        <h2>Today's drop</h2>
        <p>Three people picked for you today from your Browse preferences — fewer, better matches instead of endless swiping. A fresh drop lands every day.</p>
        <div class="cards" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px">
            <?php foreach ($engine->dailyDrop($userId) as $pick): ?>
                <div class="card">
                    <div class="who">
                        <img class="avatar" src="avatar.php?u=<?= urlencode((string) $pick['user_id']) ?>" alt="">
                        <div>
                            <strong><?= sd_e((string) ($pick['display_name'] ?: $pick['user_id'])) ?></strong>
                            <?= !empty($pick['verified']) ? '<span class="pill ok">✓ verified</span>' : '' ?><br>
                            <span style="color:#a294ad;font-size:12.5px">match <?= (int) $pick['match_score'] ?> · ~<?= sd_e((string) $pick['zip_distance_km']) ?> km</span>
                        </div>
                    </div>
                    <form method="post" style="background:none;border:0;padding:0;margin:6px 0 0">
                        <input type="hidden" name="action" value="start_chat">
                        <input type="hidden" name="user_id" value="<?= sd_e((string) $pick['user_id']) ?>">
                        <button type="submit" class="act small">Start slow chat</button>
                    </form>
                </div>
            <?php endforeach; ?>
        </div>
    </section>
    <section>
        <h2>Your matches</h2>
        <?php foreach ($engine->matchesFor($userId, ['limit' => 10]) as $match): ?>
            <div class="card" style="margin-bottom:10px">
                <div class="who" style="margin-bottom:6px">
                    <img class="avatar" src="avatar.php?u=<?= urlencode((string) $match['user_id']) ?>" alt="">
                    <strong><?= sd_e((string) ($match['display_name'] ?: $match['user_id'])) ?></strong>
                    <?= !empty($match['verified']) ? '<span class="pill ok">✓ verified</span>' : '' ?>
                    <?= ($match['dating_type'] ?? '') !== '' ? '<span class="pill">' . sd_e(str_replace('_', ' ', (string) $match['dating_type'])) . '</span>' : '' ?>
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
