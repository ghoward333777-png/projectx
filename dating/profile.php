<?php

declare(strict_types=1);

require_once __DIR__ . '/SlowDatingEngine.php';
require_once __DIR__ . '/ui.php';

session_start();

/**
 * Profile — the page behind every thumbnail. Browse, Search, Matches,
 * Communities, and the Daily Drop all link here: profile.php?u=<member>.
 * Shows the member's picture, facts, prompts, communities, videos, and
 * popularity; viewing someone else records a profile view (their
 * popularity and profile-ad earnings). On your own profile the page
 * carries the public/private picture upload forms.
 *
 * Private pictures are served fuzzed (photo.php?private=<id>) unless the
 * viewer is the owner, a premium member, or a chat partner the owner
 * invited by choosing their private picture for that chat.
 */

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

$targetId = (string) ($_GET['u'] ?? '');
if ($targetId === '' && $userId !== null) {
    $targetId = $userId;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && $userId !== null) {
    try {
        switch ((string) ($_POST['action'] ?? '')) {
            case 'start_chat':
                $engine->startChat($userId, (string) ($_POST['user_id'] ?? ''));
                $notice = 'Chat started — slow-chat pacing applies for the first 30 days.';
                break;
            case 'swipe':
                $result = $engine->recordSwipe($userId, (string) ($_POST['user_id'] ?? ''), (string) ($_POST['swipe'] ?? ''));
                if ($result['mutual']) {
                    $engine->startChat($userId, $result['target_id']);
                    $notice = 'It\'s mutual — you both liked each other! A slow chat is waiting in your Chats tab.';
                } elseif ($result['action'] === 'like') {
                    $notice = 'Liked. If they like you back, a chat opens for you both.';
                }
                break;
            case 'block':
                $engine->blockMember($userId, (string) ($_POST['user_id'] ?? ''));
                $notice = 'Blocked. They can no longer message or chat with you, and you won\'t see each other in Browse or Matches.';
                break;
            case 'unblock':
                $engine->unblockMember($userId, (string) ($_POST['user_id'] ?? ''));
                $notice = 'Unblocked — messaging between you is open again.';
                break;
            case 'upload_photo':
                $upload = $_FILES['photo'] ?? null;
                if (!is_array($upload) || ($upload['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK) {
                    throw new InvalidArgumentException('Choose a JPEG, PNG, or WebP photo up to 2 MB.');
                }
                $slot = (string) ($_POST['slot'] ?? 'public');
                $engine->setMemberPhoto($userId, (string) file_get_contents((string) $upload['tmp_name']), (string) $upload['type'], $slot);
                $notice = $slot === 'private'
                    ? 'Private picture saved. Others see it fuzzed until you invite them (premium members see it sharp).'
                    : 'Real picture saved.';
                break;
        }
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
    }
}

if ($userId === null) {
    sd_page_open('Profile', 'SlowDating · member profile');
    ?>
    <section>
        <h2>Sign in to view profiles</h2>
        <p>Profiles are for members. <a href="index.php">Sign in or create a free account</a> to see
            this member's pictures, prompts, and compatibility with you.</p>
    </section>
    <?php
    sd_page_close();
    exit;
}

$view = null;
try {
    $view = $engine->profileView($userId, $targetId);
} catch (Throwable $exception) {
    $view = null;
}

if ($view === null) {
    sd_page_open('Profile', 'SlowDating · member profile');
    sd_flash($error, $notice);
    ?>
    <section>
        <h2>Member not found</h2>
        <p>This profile doesn't exist (or was removed). <a href="browse.php">Back to Browse</a>.</p>
    </section>
    <?php
    sd_page_close();
    exit;
}

$profile = (array) $view['profile'];
$name = (string) ($profile['display_name'] ?: $view['user_id']);
$own = $targetId === $userId;
$labels = static fn (string $value): string => ucwords(str_replace('_', ' ', $value));
$sharedInterests = (array) ($view['shared_interests'] ?? []);
$sharedHobbies = (array) ($view['shared_hobbies'] ?? []);

sd_page_open($name, $own ? 'SlowDating · your profile as members see it' : 'SlowDating · member profile');
sd_flash($error, $notice);
?>
<section>
    <div class="who" style="align-items:flex-start;gap:18px;flex-wrap:wrap">
        <img class="avatar" style="width:160px;height:160px" src="avatar.php?u=<?= urlencode((string) $view['user_id']) ?>" alt="Profile picture of <?= sd_e($name) ?>">
        <div style="flex:1;min-width:240px">
            <h2 style="font-size:28px;margin:0"><?= sd_e($name) ?>
                <?= !empty($view['verified']) ? '<span class="pill ok">✓ verified</span>' : '' ?></h2>
            <p style="margin:6px 0">
                <?= (int) ($profile['age'] ?? 0) > 0 ? (int) $profile['age'] . ' · ' : '' ?>
                <?= ($profile['gender'] ?? '') !== '' ? sd_e($labels((string) $profile['gender'])) . ' · ' : '' ?>
                <?= ($profile['dating_type'] ?? '') !== '' ? 'looking for ' . sd_e(str_replace('_', ' ', (string) $profile['dating_type'])) : '' ?>
                <?= isset($view['zip_distance_km']) ? ' · ~' . sd_e((string) $view['zip_distance_km']) . ' km from you' : '' ?>
            </p>
            <div>
                <span class="pill">popularity <?= (int) $view['popularity_score'] ?></span>
                <span class="pill">trend: <?= sd_e((string) $view['popularity_trend']) ?></span>
                <?php if (isset($view['match_score'])): ?>
                    <span class="pill" style="background:#4a2440;color:#ffd4e5">match with you: <?= (int) $view['match_score'] ?></span>
                <?php endif; ?>
            </div>
            <?php if (!$own): ?>
                <?php $blockedByMe = $engine->hasBlocked($userId, $targetId); ?>
                <div style="display:flex;gap:10px;flex-wrap:wrap">
                    <?php if (!$blockedByMe): ?>
                    <form method="post" style="background:none;border:0;padding:0;margin:0">
                        <input type="hidden" name="action" value="swipe">
                        <input type="hidden" name="user_id" value="<?= sd_e((string) $view['user_id']) ?>">
                        <input type="hidden" name="swipe" value="like">
                        <button type="submit">♥ Like</button>
                    </form>
                    <form method="post" style="background:none;border:0;padding:0;margin:0">
                        <input type="hidden" name="action" value="start_chat">
                        <input type="hidden" name="user_id" value="<?= sd_e((string) $view['user_id']) ?>">
                        <button type="submit">Start slow chat</button>
                    </form>
                    <?php endif; ?>
                    <form method="post" style="background:none;border:0;padding:0;margin:0">
                        <input type="hidden" name="action" value="<?= $blockedByMe ? 'unblock' : 'block' ?>">
                        <input type="hidden" name="user_id" value="<?= sd_e((string) $view['user_id']) ?>">
                        <button type="submit" style="background:#3a2a3e;color:#ffc4da"><?= $blockedByMe ? 'Unblock' : 'Block' ?></button>
                    </form>
                </div>
                <?php if ($blockedByMe): ?>
                    <p style="margin:8px 0 0;color:#a294ad;font-size:13px">You blocked <?= sd_e($name) ?> — no messages or chats can pass between you until you unblock them.</p>
                <?php endif; ?>
            <?php else: ?>
                <p style="margin:10px 0 0;color:#a294ad">This is your profile exactly as other members see it.
                    <a href="index.php" style="color:#ffb8d2">Edit your details in the member app</a>.</p>
            <?php endif; ?>
        </div>
    </div>
    <?php if (!$own && !$view['can_see_real_photos']): ?>
        <p style="margin:12px 0 0;color:#a294ad;font-size:13px">Pictures come second here: you'll see
            <?= sd_e($name) ?>'s real picture once your chat together is
            <?= (int) $engine->photoRevealDays() ?> day<?= $engine->photoRevealDays() === 1 ? '' : 's' ?> old —
            or immediately with the premium "Peek early" perk.</p>
    <?php endif; ?>
</section>

<section>
    <h2>Their pictures</h2>
    <div class="grid">
        <div class="card">
            <strong>Artwork</strong><br>
            <img class="avatar" style="width:120px;height:120px;margin-top:8px" src="avatar.php?u=<?= urlencode((string) $view['user_id']) ?>&art=1" alt="Generated artwork">
            <p style="margin:8px 0 0;font-size:12.5px;color:#a294ad">Every member's generated artwork — always visible.</p>
        </div>
        <div class="card">
            <strong>Real picture<?= $view['pictures']['public'] ? '' : ' · none yet' ?></strong><br>
            <?php if ($view['pictures']['public'] && ($own || $view['can_see_real_photos'])): ?>
                <img class="avatar" style="width:120px;height:120px;margin-top:8px" src="<?= $own ? 'photo.php?slot=public' : 'avatar.php?u=' . urlencode((string) $view['user_id']) ?>" alt="Real picture">
                <p style="margin:8px 0 0;font-size:12.5px;color:#a294ad"><?= $own ? 'What members with photo access see.' : 'You have photo access — chat aged past the reveal timeframe, or Peek early.' ?></p>
            <?php elseif ($view['pictures']['public']): ?>
                <p style="margin:8px 0 0;font-size:12.5px;color:#a294ad">Uploaded, but not revealed to you yet — the reveal timeframe or the premium Peek early perk unlocks it.</p>
            <?php else: ?>
                <p style="margin:8px 0 0;font-size:12.5px;color:#a294ad">No real picture uploaded yet.</p>
            <?php endif; ?>
        </div>
        <div class="card">
            <strong>Private picture<?= $view['private_photo'] === 'none' ? ' · none yet' : '' ?></strong><br>
            <?php if ($view['private_photo'] !== 'none'): ?>
                <img class="avatar" style="width:120px;height:120px;margin-top:8px" src="photo.php?private=<?= urlencode((string) $view['user_id']) ?>" alt="Private picture<?= $view['private_photo'] === 'fuzzed' ? ' (fuzzed)' : '' ?>">
                <?php if ($view['private_photo'] === 'fuzzed'): ?>
                    <p style="margin:8px 0 0;font-size:12.5px;color:#a294ad">Fuzzed out. It sharpens when <?= sd_e($name) ?> invites you — by choosing their private picture in a chat with you — or immediately for premium members.</p>
                <?php else: ?>
                    <p style="margin:8px 0 0;font-size:12.5px;color:#a294ad"><?= $own ? 'Your private picture — others see it fuzzed until you invite them in a chat.' : 'Shown sharp: you were invited, or you hold a premium membership.' ?></p>
                <?php endif; ?>
            <?php else: ?>
                <p style="margin:8px 0 0;font-size:12.5px;color:#a294ad">No private picture uploaded yet.</p>
            <?php endif; ?>
        </div>
    </div>
</section>

<?php if ($own): ?>
<section>
    <h2>Upload your pictures</h2>
    <p>Your <strong style="color:#f3eef6">real picture</strong> appears on cards once a viewer earns photo
        access; your <strong style="color:#f3eef6">private picture</strong> shows on your profile fuzzed out —
        sharp only for premium members and the chat partners you invite.</p>
    <div class="grid">
        <div class="card">
            <strong>Real picture (public)</strong>
            <form method="post" enctype="multipart/form-data" style="background:none;border:0;padding:0;margin:0">
                <input type="hidden" name="action" value="upload_photo">
                <input type="hidden" name="slot" value="public">
                <input type="file" name="photo" accept="image/jpeg,image/png,image/webp" required>
                <button type="submit" style="margin-top:10px">Save real picture</button>
            </form>
        </div>
        <div class="card">
            <strong>Private picture</strong>
            <form method="post" enctype="multipart/form-data" style="background:none;border:0;padding:0;margin:0">
                <input type="hidden" name="action" value="upload_photo">
                <input type="hidden" name="slot" value="private">
                <input type="file" name="photo" accept="image/jpeg,image/png,image/webp" required>
                <button type="submit" style="margin-top:10px">Save private picture</button>
            </form>
        </div>
    </div>
</section>
<?php endif; ?>

<section>
    <h2>About <?= sd_e($name) ?></h2>
    <div class="grid">
        <?php
        $facts = [
            'Occupation' => $labels((string) ($profile['occupation_category'] ?? '')),
            'Education' => $labels((string) ($profile['education'] ?? '')),
            'Faith' => $labels((string) ($profile['faith'] ?? '')),
            'Politics' => $labels((string) ($profile['politics'] ?? '')),
            'Income' => str_replace('_', '–', (string) ($profile['income_range'] ?? '')),
            'Automobile' => $labels((string) ($profile['automobile'] ?? '')),
            'Family plans' => $labels((string) ($profile['family_plans'] ?? '')),
            'Smoking' => $labels((string) ($profile['smoking'] ?? '')),
            'Drinking' => $labels((string) ($profile['drinking'] ?? '')),
            'Pets' => $labels((string) ($profile['pets'] ?? '')),
        ];
        foreach ($facts as $label => $value):
            if (trim($value) === '') {
                continue;
            }
            ?>
            <div class="card"><strong><?= sd_e($label) ?></strong><br><span style="color:#c9bfd2"><?= sd_e($value) ?></span></div>
        <?php endforeach; ?>
    </div>
    <div style="margin-top:12px">
        <?php foreach ((array) ($profile['interests'] ?? []) as $interest): ?>
            <span class="pill"<?= in_array($interest, $sharedInterests, true) ? ' style="background:#4a2440;color:#ffd4e5"' : '' ?>><?= in_array($interest, $sharedInterests, true) ? 'both: ' : '' ?><?= sd_e((string) $interest) ?></span>
        <?php endforeach; ?>
        <?php foreach ((array) ($profile['hobbies'] ?? []) as $hobby): ?>
            <span class="pill"<?= in_array($hobby, $sharedHobbies, true) ? ' style="background:#4a2440;color:#ffd4e5"' : '' ?>><?= in_array($hobby, $sharedHobbies, true) ? 'both: ' : '' ?><?= sd_e((string) $hobby) ?></span>
        <?php endforeach; ?>
        <?php foreach ((array) ($profile['outdoor_activities'] ?? []) as $activity): ?>
            <span class="pill"><?= sd_e((string) $activity) ?></span>
        <?php endforeach; ?>
    </div>
</section>

<?php if ((array) $view['prompts'] !== []): ?>
<section>
    <h2>In their own words</h2>
    <?php foreach ((array) $view['prompts'] as $prompt): ?>
        <div class="card" style="margin-bottom:10px">
            <strong><?= sd_e((string) $prompt['question']) ?></strong>
            <p style="margin:6px 0 0">“<?= sd_e((string) $prompt['answer']) ?>”</p>
        </div>
    <?php endforeach; ?>
</section>
<?php endif; ?>

<?php if ((array) $view['communities'] !== []): ?>
<section>
    <h2>Communities</h2>
    <?php foreach ((array) $view['communities'] as $slug): ?>
        <span class="pill"><?= sd_e(SlowDatingEngine::COMMUNITIES[$slug] ?? (string) $slug) ?></span>
    <?php endforeach; ?>
</section>
<?php endif; ?>

<?php if ((array) $view['videos'] !== []): ?>
<section>
    <h2>Profile video<?= count((array) $view['videos']) === 1 ? '' : 's' ?></h2>
    <div class="grid">
        <?php foreach ((array) $view['videos'] as $video): ?>
            <div class="card">
                <iframe width="100%" height="200" src="<?= sd_e((string) $video['embed_url']) ?>" title="Profile video" frameborder="0" allowfullscreen></iframe>
            </div>
        <?php endforeach; ?>
    </div>
</section>
<?php endif; ?>

<section>
    <h2>Premium Members Only gallery</h2>
    <?php
    $gallery = null;
    $galleryError = null;
    try {
        $gallery = $engine->viewGallery($userId, $targetId);
    } catch (Throwable $exception) {
        $galleryError = $exception->getMessage();
    }
    ?>
    <?php if ($gallery !== null && (array) $gallery['photos'] !== []): ?>
        <div class="grid">
            <?php foreach ((array) $gallery['photos'] as $photo): ?>
                <div class="card">
                    <img style="width:100%;border-radius:10px" src="photo.php?gallery=<?= urlencode((string) $photo['photo_id']) ?>" alt="Gallery photo">
                    <?php if ((string) $photo['caption'] !== ''): ?>
                        <p style="margin:6px 0 0;font-size:12.5px;color:#a294ad"><?= sd_e((string) $photo['caption']) ?></p>
                    <?php endif; ?>
                </div>
            <?php endforeach; ?>
        </div>
    <?php elseif ($galleryError !== null): ?>
        <p style="color:#a294ad"><?= sd_e($galleryError) ?></p>
    <?php else: ?>
        <p style="color:#a294ad"><?= $own ? 'Your gallery is empty — add photos from Perks & income.' : 'No gallery photos yet.' ?></p>
    <?php endif; ?>
</section>

<p class="links" style="margin-top:16px"><a href="browse.php">← Back to Browse</a></p>

<?php sd_page_close(); ?>
