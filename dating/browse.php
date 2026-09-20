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
                $engine->updatePreferences($userId, $_POST + ['shared_categories' => (array) ($_POST['shared_categories'] ?? [])]);
                $notice = 'Preferences saved — Browse now reflects them.';
                break;
            case 'start_chat':
                $engine->startChat($userId, (string) ($_POST['user_id'] ?? ''));
                $notice = 'Chat started — slow-chat pacing applies for the first 30 days.';
                break;
            case 'swipe':
                $result = $engine->recordSwipe($userId, (string) ($_POST['user_id'] ?? ''), (string) ($_POST['swipe'] ?? ''));
                if ($result['mutual']) {
                    $chat = $engine->startChat($userId, $result['target_id']);
                    $notice = 'It\'s mutual — you both liked each other! A slow chat is waiting in your Chats tab.';
                } elseif ($result['action'] === 'like') {
                    $notice = 'Liked. If they like you back, a chat opens for you both.';
                }
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
$view = (string) ($_GET['view'] ?? 'grid');
if (!in_array($view, ['grid', 'swipe', 'top10', 'top20'], true)) {
    $view = 'grid';
}
$matches = $view === 'top10' ? $engine->topMatches($userId, 10)
    : ($view === 'top20' ? $engine->topMatches($userId, 20) : $engine->browseFor($userId));
$views = ['grid' => 'Grid', 'swipe' => 'Swipe', 'top10' => 'Top 10', 'top20' => 'Top 20'];
?>
<section>
    <h2 style="margin-bottom:6px">How do you want to look?</h2>
    <p class="links" style="margin:0">
        <?php foreach ($views as $key => $label): ?>
            <a href="?view=<?= sd_e($key) ?>"<?= $view === $key ? ' style="font-weight:800;text-decoration:underline"' : '' ?>><?= sd_e($label) ?></a>
        <?php endforeach; ?>
    </p>
</section>
<?php if ($view === 'swipe'): ?>
    <?php $candidate = $engine->nextSwipe($userId); ?>
    <section>
        <h2>Swipe — one at a time</h2>
        <?php if ($candidate === null): ?>
            <p>You're through everyone who fits your preferences. Widen them on the Grid view, or come back
                tomorrow — the pool refreshes as new members join.</p>
        <?php else: ?>
            <div class="card" style="max-width:420px">
                <div class="who">
                    <img class="avatar" style="width:96px;height:96px" src="avatar.php?u=<?= urlencode((string) $candidate['user_id']) ?>" alt="">
                    <div>
                        <strong style="font-size:20px"><?= sd_e((string) ($candidate['display_name'] ?: $candidate['user_id'])) ?></strong>
                        <?= !empty($candidate['verified']) ? '<span class="pill ok">✓ verified</span>' : '' ?><br>
                        <span style="color:#a294ad">match <?= (int) $candidate['match_score'] ?> · popularity <?= (int) $candidate['popularity_score'] ?> · ~<?= sd_e((string) $candidate['zip_distance_km']) ?> km</span>
                    </div>
                </div>
                <div style="margin:8px 0">
                    <?php foreach (array_slice((array) $candidate['shared_interests'], 0, 4) as $interest): ?>
                        <span class="pill">both: <?= sd_e((string) $interest) ?></span>
                    <?php endforeach; ?>
                </div>
                <div style="display:flex;gap:10px">
                    <form method="post" style="background:none;border:0;padding:0;margin:0">
                        <input type="hidden" name="action" value="swipe">
                        <input type="hidden" name="user_id" value="<?= sd_e((string) $candidate['user_id']) ?>">
                        <input type="hidden" name="swipe" value="pass">
                        <button type="submit" class="quiet" style="margin:0">Pass</button>
                    </form>
                    <form method="post" style="background:none;border:0;padding:0;margin:0">
                        <input type="hidden" name="action" value="swipe">
                        <input type="hidden" name="user_id" value="<?= sd_e((string) $candidate['user_id']) ?>">
                        <input type="hidden" name="swipe" value="like">
                        <button type="submit" class="act" style="margin:0">Like</button>
                    </form>
                </div>
            </div>
        <?php endif; ?>
    </section>
<?php endif; ?>
<?php if ($view === 'grid'): ?>
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
    <h3 style="margin:14px 0 4px">Must match (leave any of these on "Any")</h3>
    <div class="grid">
        <div><label>Faith</label>
            <select name="faith">
                <option value="">Any</option>
                <?php foreach (['christian', 'catholic', 'jewish', 'muslim', 'hindu', 'buddhist', 'spiritual', 'none'] as $option): ?>
                    <option value="<?= $option ?>"<?= ($preferences['faith'] ?? '') === $option ? ' selected' : '' ?>><?= ucfirst($option) ?></option>
                <?php endforeach; ?>
            </select>
        </div>
        <div><label>Politics</label>
            <select name="politics">
                <option value="">Any</option>
                <?php foreach (['liberal', 'conservative', 'moderate', 'apolitical'] as $option): ?>
                    <option value="<?= $option ?>"<?= ($preferences['politics'] ?? '') === $option ? ' selected' : '' ?>><?= ucfirst($option) ?></option>
                <?php endforeach; ?>
            </select>
        </div>
        <div><label>Income</label>
            <select name="income_range">
                <option value="">Any</option>
                <?php foreach (SlowDatingEngine::INCOME_RANGES as $option): ?>
                    <option value="<?= $option ?>"<?= ($preferences['income_range'] ?? '') === $option ? ' selected' : '' ?>><?= str_replace('_', '–', $option) ?></option>
                <?php endforeach; ?>
            </select>
        </div>
        <div><label>Education</label>
            <select name="education">
                <option value="">Any</option>
                <?php foreach (SlowDatingEngine::EDUCATION_LEVELS as $option): ?>
                    <option value="<?= $option ?>"<?= ($preferences['education'] ?? '') === $option ? ' selected' : '' ?>><?= ucwords(str_replace('_', ' ', $option)) ?></option>
                <?php endforeach; ?>
            </select>
        </div>
        <div><label>Occupation</label>
            <select name="occupation_category">
                <option value="">Any</option>
                <?php foreach (['tech', 'finance', 'medical', 'legal', 'arts', 'education', 'service', 'government', 'entrepreneur', 'marketing'] as $option): ?>
                    <option value="<?= $option ?>"<?= ($preferences['occupation_category'] ?? '') === $option ? ' selected' : '' ?>><?= ucfirst($option) ?></option>
                <?php endforeach; ?>
            </select>
        </div>
        <div><label>Automobile</label>
            <select name="automobile">
                <option value="">Any</option>
                <?php foreach (SlowDatingEngine::AUTOMOBILES as $option): ?>
                    <option value="<?= $option ?>"<?= ($preferences['automobile'] ?? '') === $option ? ' selected' : '' ?>><?= ucfirst($option) ?></option>
                <?php endforeach; ?>
            </select>
        </div>
        <div><label>Family plans</label>
            <select name="family_plans">
                <option value="">Any</option>
                <?php foreach (SlowDatingEngine::FAMILY_PLANS as $option): ?>
                    <option value="<?= $option ?>"<?= ($preferences['family_plans'] ?? '') === $option ? ' selected' : '' ?>><?= ucwords(str_replace('_', ' ', $option)) ?></option>
                <?php endforeach; ?>
            </select>
        </div>
        <div><label>Smoking</label>
            <select name="smoking">
                <option value="">Any</option>
                <?php foreach (SlowDatingEngine::SMOKING as $option): ?>
                    <option value="<?= $option ?>"<?= ($preferences['smoking'] ?? '') === $option ? ' selected' : '' ?>><?= ucfirst($option) ?></option>
                <?php endforeach; ?>
            </select>
        </div>
        <div><label>Drinking</label>
            <select name="drinking">
                <option value="">Any</option>
                <?php foreach (SlowDatingEngine::DRINKING as $option): ?>
                    <option value="<?= $option ?>"<?= ($preferences['drinking'] ?? '') === $option ? ' selected' : '' ?>><?= ucfirst($option) ?></option>
                <?php endforeach; ?>
            </select>
        </div>
        <div><label>Pets</label>
            <select name="pets">
                <option value="">Any</option>
                <?php foreach (SlowDatingEngine::PETS as $option): ?>
                    <option value="<?= $option ?>"<?= ($preferences['pets'] ?? '') === $option ? ' selected' : '' ?>><?= ucfirst($option) ?></option>
                <?php endforeach; ?>
            </select>
        </div>
    </div>
    <h3 style="margin:14px 0 4px">Must share (generic classifications — pick as many as matter)</h3>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(180px,1fr))">
        <?php $chosenCategories = (array) ($preferences['shared_categories'] ?? []); ?>
        <?php foreach (SlowDatingEngine::INTEREST_CATEGORIES as $slug => $label): ?>
            <label style="display:flex;gap:8px;align-items:center;font-weight:400;margin:0">
                <input type="checkbox" name="shared_categories[]" value="<?= sd_e($slug) ?>" style="width:auto"
                    <?= in_array($slug, $chosenCategories, true) ? 'checked' : '' ?>>
                <?= sd_e($label) ?>
            </label>
        <?php endforeach; ?>
    </div>
    <label>Specific shared interests (optional, comma separated — advanced)</label>
    <input name="interests" value="<?= sd_e(implode(', ', (array) $preferences['interests'])) ?>" placeholder="jazz, hiking">
    <button type="submit">Save preferences</button>
</form>
<?php endif; ?>

<?php if ($view !== 'swipe'): ?>
<section>
    <h2><?= $view === 'grid' ? 'Your best matches' : 'Your ' . sd_e($views[$view]) . ' matches across the whole community' ?></h2>
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
                            <strong><?= sd_e((string) ($match['display_name'] ?: $match['user_id'])) ?></strong>
                            <?= !empty($match['verified']) ? '<span class="pill ok">✓ verified</span>' : '' ?><br>
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
<?php endif; ?>

<?php sd_page_close(); ?>
