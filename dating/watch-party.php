<?php

declare(strict_types=1);

require_once __DIR__ . '/SlowDatingEngine.php';
require_once __DIR__ . '/ui.php';

session_start();

/**
 * Watch Party — a movie-night date on the web. Every day the platform
 * schedules one film from its independent playlist of 1,000 romance
 * films; a couple opens this page, presses play together, and talks in
 * the chat box under the player. Either partner can swap in any other
 * film from the romance library. The chat is the couple's normal slow
 * chat: pacing, contact filtering, and safety rules all still apply.
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

$chatId = (string) ($_GET['chat'] ?? ($_POST['chat_id'] ?? ''));

if ($_SERVER['REQUEST_METHOD'] === 'POST' && $userId !== null) {
    try {
        switch ((string) ($_POST['action'] ?? '')) {
            case 'send':
                $engine->sendMessage((string) ($_POST['chat_id'] ?? ''), $userId, (string) ($_POST['text'] ?? ''));
                break;
            case 'pick':
                $party = $engine->chooseWatchPartyFilm((string) ($_POST['chat_id'] ?? ''), $userId, (string) ($_POST['film_id'] ?? 'daily'));
                $notice = ($_POST['film_id'] ?? '') === 'daily'
                    ? 'Back to tonight\'s scheduled movie.'
                    : 'Movie changed — you are both watching ' . $party['film']['title'] . ' (' . $party['film']['year'] . ') now.';
                break;
        }
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
    }
}

sd_page_open('Watch Party', 'SlowDating · a movie date, right here');
sd_flash($error, $notice);

if ($userId === null) {
    ?>
    <section>
        <h2>Movie night, together</h2>
        <p>Every day SlowDating schedules one film from its romance playlist of 1,000 movies. Open the Watch
            Party with your match, press play together, and talk in the chat under the player — or pick any
            other film from the library. <a href="index.php">Sign in or create a free account</a> to start.</p>
    </section>
    <?php
    sd_page_close();
    exit;
}

$chats = $engine->chatsFor($userId);
if ($chats === []) {
    ?>
    <section>
        <h2>First, find your plus-one</h2>
        <p>A watch party needs a chat partner. Head to <a href="browse.php">Browse</a> or
            <a href="index.php?tab=matches">Matches</a> and start a conversation — then come back here for movie night.</p>
    </section>
    <?php
    sd_page_close();
    exit;
}

$chatIds = array_map(static fn (array $chat): string => (string) $chat['id'], $chats);
if (!in_array($chatId, $chatIds, true)) {
    $chatId = $chatIds[0];
}
$party = $engine->watchPartyFor($chatId, $userId);
$film = $party['film'];
$scheduled = $party['scheduled'];
$chat = $engine->store()->get('chats', $chatId);
$status = $engine->chatStatus($chatId);
$otherId = '';
foreach ((array) $chat['participants'] as $participant) {
    if ($participant !== $userId) {
        $otherId = (string) $participant;
    }
}
$otherName = (string) ($engine->profile($otherId)['display_name'] ?: $otherId);

$q = trim((string) ($_GET['q'] ?? ''));
$page = max(0, (int) ($_GET['p'] ?? 0));
$perPage = 24;
$library = $engine->romanceFilms($q, $perPage, $page * $perPage);
?>

<section>
    <h2>Movie night with…</h2>
    <p class="links" style="margin:0">
        <?php foreach ($chats as $option):
            $optionId = (string) $option['id'];
            $partnerId = '';
            foreach ((array) $option['participants'] as $participant) {
                if ($participant !== $userId) {
                    $partnerId = (string) $participant;
                }
            }
            $partnerName = (string) ($engine->profile($partnerId)['display_name'] ?: $partnerId);
            ?>
            <a href="?chat=<?= sd_e($optionId) ?>"<?= $optionId === $chatId ? ' style="font-weight:800;text-decoration:underline"' : '' ?>><?= sd_e($partnerName) ?></a>
        <?php endforeach; ?>
    </p>
</section>

<section>
    <h2><?= sd_e((string) $film['title']) ?> (<?= (int) $film['year'] ?>)
        <span class="pill">#<?= (int) $film['rank'] ?> in the romance playlist</span>
        <span class="pill"><?= sd_e((string) $film['tag']) ?></span>
        <?php if ($party['custom_pick']): ?><span class="pill">your pick</span><?php endif; ?>
    </h2>
    <?php if (!$party['custom_pick']): ?>
        <p>Tonight's scheduled movie — a new film from the playlist every day, the same one for every couple.</p>
    <?php else: ?>
        <p>You swapped tonight's schedule (<?= sd_e((string) $scheduled['title']) ?>, <?= (int) $scheduled['year'] ?>) for your own pick.
            <?php if (($party['chosen_by'] ?? '') === $userId): ?>You chose this one.<?php else: ?><?= sd_e($otherName) ?> chose this one.<?php endif; ?></p>
        <form method="post" style="background:none;border:0;padding:0;margin:0 0 10px">
            <input type="hidden" name="action" value="pick">
            <input type="hidden" name="chat_id" value="<?= sd_e($chatId) ?>">
            <input type="hidden" name="film_id" value="daily">
            <button type="submit">Back to tonight's scheduled movie</button>
        </form>
    <?php endif; ?>

    <?php if (!empty($film['playable'])): ?>
        <div style="position:relative;padding-top:56.25%;border-radius:14px;overflow:hidden;background:#000">
            <iframe src="<?= sd_e((string) $film['embed_url']) ?>" title="<?= sd_e((string) $film['title']) ?>"
                    style="position:absolute;inset:0;width:100%;height:100%;border:0"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowfullscreen></iframe>
        </div>
        <p style="font-size:13px">A verified, legally free upload (public-domain classic). Press play together — playback runs on each screen.</p>
    <?php else: ?>
        <div class="card" style="padding:24px;text-align:center">
            <p style="margin:0 0 10px"><strong style="color:#fff;font-size:18px"><?= sd_e((string) $film['title']) ?> (<?= (int) $film['year'] ?>)</strong></p>
            <p style="margin:0 0 14px">This film streams on YouTube from its own distributors. Open it in a second tab,
                press play together, and keep this page for your chat.</p>
            <a href="<?= sd_e((string) $film['watch_url']) ?>" target="_blank" rel="noopener"
               style="display:inline-block;background:#ff9cc0;color:#2a0f1d;border-radius:999px;padding:11px 18px;font-weight:800;text-decoration:none">Open on YouTube</a>
        </div>
    <?php endif; ?>

    <h2 style="margin-top:18px">Talk while you watch</h2>
    <p style="margin:0 0 8px">
        <?php if ($status['unlocked']): ?>
            <span class="pill">Real-time chat</span>
        <?php else: ?>
            <span class="pill">Slow chat · <?= (int) $status['daily_message_limit'] ?> messages today · <?= (int) $status['message_size_limit'] ?> characters each</span>
        <?php endif; ?>
        <span class="pill">Contact details stay filtered until day 30</span>
    </p>
    <div class="chat-log">
        <?php foreach ((array) $chat['messages'] as $message): ?>
            <div class="msg <?= $message['sender_id'] === $userId ? 'mine' : 'theirs' ?>">
                <?= sd_e((string) $message['text']) ?>
                <small><?= $message['sender_id'] === $userId ? 'You' : sd_e($otherName) ?> · <?= sd_e(gmdate('M j, H:i', (int) $message['sent_at'])) ?>
                    <?= ((int) ($message['contact_data_removed'] ?? 0)) > 0 ? '· contact info erased' : '' ?></small>
            </div>
        <?php endforeach; ?>
    </div>
    <form method="post" style="margin-top:10px">
        <input type="hidden" name="action" value="send">
        <input type="hidden" name="chat_id" value="<?= sd_e($chatId) ?>">
        <label>Message <?= sd_e($otherName) ?></label>
        <textarea name="text" placeholder="That opening scene…" required></textarea>
        <button type="submit">Send</button>
    </form>
</section>

<section>
    <h2>The romance library — pick any film instead</h2>
    <p>The platform's independent playlist: 1,000 romance films ranked by popularity. Tonight's schedule picks
        one for everyone; your watch party can swap to any of them.</p>
    <form method="get" style="background:none;border:0;padding:0;margin:0 0 12px">
        <input type="hidden" name="chat" value="<?= sd_e($chatId) ?>">
        <label>Search the library (title, year, or era — e.g. "jazz", "1999", "golden age")</label>
        <input name="q" value="<?= sd_e($q) ?>" placeholder="The Notebook">
        <button type="submit">Search</button>
    </form>
    <p style="margin:0 0 8px;font-size:13px"><?= (int) $library['total'] ?> film<?= $library['total'] === 1 ? '' : 's' ?><?= $q !== '' ? ' matching "' . sd_e($q) . '"' : ' in the playlist' ?> · page <?= $page + 1 ?></p>
    <div class="grid">
        <?php foreach ($library['films'] as $entry): ?>
            <div class="card">
                <strong>#<?= (int) $entry['rank'] ?> · <?= sd_e((string) $entry['title']) ?></strong>
                <p style="margin:6px 0"><span class="pill"><?= (int) $entry['year'] ?></span>
                    <span class="pill"><?= sd_e((string) $entry['tag']) ?></span>
                    <?php if (!empty($entry['playable'])): ?><span class="pill" style="background:#17351f;color:#b8ffd3">plays in-page</span><?php endif; ?></p>
                <form method="post" style="background:none;border:0;padding:0;margin:0">
                    <input type="hidden" name="action" value="pick">
                    <input type="hidden" name="chat_id" value="<?= sd_e($chatId) ?>">
                    <input type="hidden" name="film_id" value="<?= sd_e((string) $entry['id']) ?>">
                    <button type="submit">Watch this instead</button>
                </form>
            </div>
        <?php endforeach; ?>
    </div>
    <p class="links" style="margin-top:12px">
        <?php if ($page > 0): ?><a href="?chat=<?= sd_e($chatId) ?>&amp;q=<?= sd_e($q) ?>&amp;p=<?= $page - 1 ?>">&#8249; Previous page</a><?php endif; ?>
        <?php if (($page + 1) * $perPage < (int) $library['total']): ?><a href="?chat=<?= sd_e($chatId) ?>&amp;q=<?= sd_e($q) ?>&amp;p=<?= $page + 1 ?>">Next page &#8250;</a><?php endif; ?>
    </p>
</section>

<?php sd_page_close();
