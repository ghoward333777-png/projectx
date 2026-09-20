<?php

declare(strict_types=1);

require_once __DIR__ . '/SlowDatingEngine.php';
require_once __DIR__ . '/ui.php';

session_start();

/**
 * Browse — the member's best matches, driven by their saved preferences:
 * who they're seeking, age range, distance, dating goal, and must-share
 * interests. Preferences persist on the account and also power the API's
 * GET /browse.
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

if ($_SERVER['REQUEST_METHOD'] === 'POST' && $userId !== null) {
    try {
        switch ((string) ($_POST['action'] ?? '')) {
            case 'preferences':
                $engine->updatePreferences($userId, $_POST);
                $notice = 'Preferences saved — Browse now reflects them.';
                break;
            case 'start_chat':
                $engine->startChat($userId, (string) ($_POST['user_id'] ?? ''));
                $notice = 'Chat started — slow-chat pacing applies for the first 30 days.';
                break;
        }
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
    }
}

sd_page_open('Browse', 'SlowDating · your best matches, your preferences');
sd_flash($error, $notice);

if ($userId === null) {
    ?>
    <section>
        <h2>Sign in to browse</h2>
        <p>Browse ranks the whole community against <em>your</em> saved preferences — who you're looking for,
            how far you'll travel, and what you must have in common.
            <a href="index.php">Sign in or create a free account</a> to start.</p>
    </section>
    <?php
    sd_page_close();
    exit;
}

$preferences = $engine->preferences($userId);
$matches = $engine->browseFor($userId);
?>
<form method="post">
    <h2>Who are you looking for?</h2>
    <input type="hidden" name="action" value="preferences">
    <div class="grid">
        <div><label>Gender</label>
            <select name="seeking_gender">
                <option value="">Anyone</option>
                <option value="female"<?= $preferences['seeking_gender'] === 'female' ? ' selected' : '' ?>>Women</option>
                <option value="male"<?= $preferences['seeking_gender'] === 'male' ? ' selected' : '' ?>>Men</option>
            </select>
        </div>
        <div><label>Age from</label><input name="age_min" type="number" min="18" value="<?= (int) $preferences['age_min'] ?>"></div>
        <div><label>Age to</label><input name="age_max" type="number" min="18" value="<?= (int) $preferences['age_max'] ?>"></div>
        <div><label>Within (km)</label><input name="max_distance_km" type="number" min="1" value="<?= (int) $preferences['max_distance_km'] ?>"></div>
        <div><label>Looking for</label>
            <select name="dating_type">
                <option value="">Any relationship type</option>
                <?php foreach (SlowDatingEngine::DATING_TYPES as $type): ?>
                    <option value="<?= sd_e($type) ?>"<?= $preferences['dating_type'] === $type ? ' selected' : '' ?>><?= sd_e(str_replace('_', ' ', $type)) ?></option>
                <?php endforeach; ?>
            </select>
        </div>
    </div>
    <label>Must share these interests (comma separated, optional)</label>
    <input name="interests" value="<?= sd_e(implode(', ', (array) $preferences['interests'])) ?>" placeholder="jazz, hiking">
    <button type="submit">Save preferences</button>
</form>

<section>
    <h2>Your best matches</h2>
    <?php if ($matches === []): ?>
        <p>No one fits these preferences yet. Widen the distance or age range, or drop a must-share
            interest — your matches update the moment you save.</p>
    <?php else: ?>
        <p><?= count($matches) ?> member<?= count($matches) === 1 ? '' : 's' ?> fit your preferences, best match first.</p>
        <div class="cards" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px">
            <?php foreach ($matches as $match): ?>
                <div class="card">
                    <div class="who">
                        <img class="avatar" src="avatar.php?u=<?= urlencode((string) $match['user_id']) ?>" alt="">
                        <div>
                            <strong><?= sd_e((string) ($match['display_name'] ?: $match['user_id'])) ?></strong><br>
                            <span style="color:#a294ad;font-size:13px">match <?= (int) $match['match_score'] ?> ·
                                popularity <?= (int) $match['popularity_score'] ?> · ~<?= sd_e((string) $match['zip_distance_km']) ?> km</span>
                        </div>
                    </div>
                    <div>
                        <?php foreach (array_slice((array) $match['shared_interests'], 0, 4) as $interest): ?>
                            <span class="pill">both: <?= sd_e((string) $interest) ?></span>
                        <?php endforeach; ?>
                        <?php foreach (array_slice((array) $match['shared_hobbies'], 0, 2) as $hobby): ?>
                            <span class="pill">both: <?= sd_e((string) $hobby) ?></span>
                        <?php endforeach; ?>
                    </div>
                    <form method="post" style="background:none;border:0;padding:0;margin:6px 0 0">
                        <input type="hidden" name="action" value="start_chat">
                        <input type="hidden" name="user_id" value="<?= sd_e((string) $match['user_id']) ?>">
                        <button type="submit">Start slow chat</button>
                    </form>
                </div>
            <?php endforeach; ?>
        </div>
    <?php endif; ?>
</section>

<?php sd_page_close(); ?>
