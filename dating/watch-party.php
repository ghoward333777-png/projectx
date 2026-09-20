<?php

declare(strict_types=1);

require_once __DIR__ . '/SlowDatingEngine.php';
require_once __DIR__ . '/ui.php';

session_start();

/**
 * Watch Party — a movie-night date on the web. The player and the
 * couple's chat live on one page: video on top, a scrolling message
 * panel with a text entry area (and image sharing) directly under it.
 * Every day the platform schedules one film from its playlist of 1,000
 * romance films; either partner can swap in any other film from the
 * library. The chat is the couple's normal slow chat: pacing, contact
 * filtering, and safety rules all still apply.
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
                $text = (string) ($_POST['text'] ?? '');
                $upload = $_FILES['image'] ?? null;
                if ($upload !== null && (int) $upload['error'] === UPLOAD_ERR_OK) {
                    $engine->sendImageMessage(
                        (string) ($_POST['chat_id'] ?? ''),
                        $userId,
                        (string) file_get_contents((string) $upload['tmp_name']),
                        (string) $upload['type'],
                        $text,
                    );
                } else {
                    $engine->sendMessage((string) ($_POST['chat_id'] ?? ''), $userId, $text);
                }
                break;
            case 'pick':
                $party = $engine->chooseWatchPartyFilm((string) ($_POST['chat_id'] ?? ''), $userId, (string) ($_POST['film_id'] ?? 'daily'));
                $notice = ($_POST['film_id'] ?? '') === 'daily'
                    ? 'Back to tonight\'s scheduled movie.'
                    : 'Movie changed — you are both watching ' . $party['film']['title']
                        . ((int) $party['film']['year'] > 0 ? ' (' . $party['film']['year'] . ')' : '') . ' now.';
                break;
        }
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
    }
}

sd_page_open('Watch Party', 'SlowDating · a movie date, right here');
?>
<style>
    /* Player + chat, one column — the Watch Party layout. */
    #watchparty { display: flex; flex-direction: column; gap: 16px; }
    #watchparty .video-wrapper {
        position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden;
        border-radius: 12px; box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
        border: 1px solid #1f2937; background: #020617;
    }
    #watchparty .video-wrapper iframe { position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: 0; }
    #watchparty .video-fallback {
        position: absolute; top: 0; left: 0; width: 100%; height: 100%;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        gap: 12px; text-align: center; padding: 24px;
    }
    #watchparty .chat {
        display: flex; flex-direction: column; gap: 12px;
        background: #020617; border-radius: 12px; padding: 12px; border: 1px solid #1f2937;
        margin-top: 0;
    }
    #watchparty .chat-header {
        display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px;
        padding-bottom: 8px; border-bottom: 1px solid #1f2937;
    }
    #watchparty .chat-header h2 { font-size: 16px; font-weight: 600; margin: 0; }
    #watchparty .chat-header span { font-size: 12px; color: #9ca3af; }
    #watchparty .messages {
        height: max(340px, 48vh); overflow-y: auto; display: flex; flex-direction: column; gap: 8px; padding-right: 4px;
    }
    #watchparty .message {
        display: inline-flex; flex-direction: column; max-width: 70%; padding: 8px 10px;
        border-radius: 10px; background: #111827; border: 1px solid #1f2937; font-size: 13px; gap: 6px;
        align-self: flex-start; color: #e5e7eb;
    }
    #watchparty .message.me { align-self: flex-end; background: #1d4ed8; border-color: #1d4ed8; color: #fff; }
    #watchparty .message-meta { display: flex; justify-content: space-between; gap: 12px; font-size: 11px; color: #cbd5e1; opacity: .85; }
    #watchparty .message-images { display: flex; flex-wrap: wrap; gap: 6px; }
    #watchparty .message-images img {
        max-width: 120px; max-height: 120px; border-radius: 6px; border: 1px solid #1f2937; object-fit: cover;
    }
    #watchparty .input-area { display: flex; flex-direction: column; gap: 8px; border-bottom: 1px solid #1f2937; padding-bottom: 10px; background: none; border-radius: 0; padding-left: 0; padding-right: 0; padding-top: 0; margin-top: 0; border-left: 0; border-right: 0; border-top: 0; }
    #watchparty .input-row { display: flex; gap: 8px; align-items: flex-end; }
    #watchparty .input-row textarea {
        flex: 1; resize: vertical; min-height: 90px; max-height: 220px; padding: 10px; border-radius: 8px;
        border: 1px solid #374151; background: #020617; color: #e5e7eb; font-size: 13px; width: auto;
    }
    #watchparty .input-row textarea:focus { outline: none; border-color: #3b82f6; box-shadow: 0 0 0 1px #3b82f6; }
    #watchparty .input-controls { display: flex; flex-direction: column; gap: 6px; align-items: flex-end; }
    #watchparty .file-label {
        display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 999px;
        border: 1px dashed #4b5563; color: #9ca3af; font-size: 12px; cursor: pointer; background: #020617; margin: 0;
    }
    #watchparty .file-label input { display: none; }
    #watchparty .send-btn {
        background: #1d4ed8; color: #fff; border: 0; border-radius: 8px; padding: 10px 18px;
        font-size: 13px; font-weight: 700; cursor: pointer; margin: 0;
    }
    #watchparty .send-btn:hover { background: #3b82f6; }
    #watchparty .hint { font-size: 11.5px; color: #9ca3af; }
</style>
<?php
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
$filmLabel = $film['title'] . ((int) $film['year'] > 0 ? ' (' . $film['year'] . ')' : '');

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
        <span class="pill" style="margin-left:8px"><?= sd_e((string) $film['title']) ?> · #<?= (int) $film['rank'] ?> in the playlist<?= $party['custom_pick'] ? ' · your pick' : ' · tonight\'s schedule' ?></span>
        <?php if ($party['custom_pick']): ?>
        <form method="post" style="display:inline;background:none;border:0;padding:0;margin:0">
            <input type="hidden" name="action" value="pick">
            <input type="hidden" name="chat_id" value="<?= sd_e($chatId) ?>">
            <input type="hidden" name="film_id" value="daily">
            <button type="submit" style="margin:0;padding:6px 12px;font-size:12px">Back to the scheduled movie (<?= sd_e((string) $scheduled['title']) ?>)</button>
        </form>
        <?php endif; ?>
    </p>
</section>

<div id="watchparty">
    <!-- Player: every film plays inside the page (YouTube's ads run in
         the embed), through the curated id or the resolved best upload. -->
    <div class="video-wrapper">
        <?php $embedSrc = (string) $film['embed_url'] . '?rel=0' . ($party['playlist'] !== [] ? '&playlist=' . implode(',', $party['playlist']) : ''); ?>
        <?php if (!empty($film['embed_url'])): ?>
            <iframe src="<?= sd_e($embedSrc) ?>" title="<?= sd_e((string) $film['title']) ?>"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowfullscreen></iframe>
        <?php else: ?>
            <div class="video-fallback">
                <strong style="color:#fff;font-size:18px"><?= sd_e($filmLabel) ?></strong>
                <span style="color:#9ca3af;font-size:13px;max-width:48ch">Finding this film's stream — refresh in a moment.</span>
            </div>
        <?php endif; ?>
    </div>

    <!-- Chat -->
    <div class="chat">
        <div class="chat-header">
            <h2>Watching with <?= sd_e($otherName) ?></h2>
            <span>
                <?php if ($status['unlocked']): ?>
                    Real-time chat · contact sharing open
                <?php else: ?>
                    Slow chat · <?= (int) $status['daily_message_limit'] ?> messages today · <?= (int) $status['message_size_limit'] ?> characters each · contact details filtered
                <?php endif; ?>
            </span>
        </div>
        <!-- The entry area sits at the TOP of the chat, right under the
             player, and stays there as the chat grows; the newest message
             appears directly beneath it. -->
        <form class="input-area" method="post" enctype="multipart/form-data">
            <input type="hidden" name="action" value="send">
            <input type="hidden" name="chat_id" value="<?= sd_e($chatId) ?>">
            <div class="input-row">
                <textarea name="text" placeholder="Say something about the movie…"<?= $status['unlocked'] ? '' : ' maxlength="' . (int) $status['message_size_limit'] . '"' ?>></textarea>
                <div class="input-controls">
                    <label class="file-label" id="wp-filelabel">
                        <input type="file" name="image" accept="image/jpeg,image/png,image/webp" id="wp-file">
                        <span id="wp-filename">📎 Attach image</span>
                    </label>
                    <button type="submit" class="send-btn">Send</button>
                </div>
            </div>
            <span class="hint">JPEG, PNG, or WebP up to 2 MB. An attached image sends with your text as its caption.
                Contact details stay filtered until the chat unlocks. Newest messages appear right below.</span>
        </form>
        <div class="messages" id="wp-messages">
            <?php foreach (array_reverse((array) $chat['messages']) as $message): ?>
                <div class="message<?= $message['sender_id'] === $userId ? ' me' : '' ?>">
                    <?php if (isset($message['image'])): ?>
                        <div class="message-images">
                            <img src="chatimage.php?chat=<?= urlencode($chatId) ?>&amp;m=<?= urlencode((string) $message['message_id']) ?>" alt="Shared image">
                        </div>
                    <?php endif; ?>
                    <?php if ((string) $message['text'] !== ''): ?><span><?= sd_e((string) $message['text']) ?></span><?php endif; ?>
                    <div class="message-meta">
                        <span><?= $message['sender_id'] === $userId ? 'You' : sd_e($otherName) ?></span>
                        <span><?= sd_e(gmdate('M j, H:i', (int) $message['sent_at'])) ?><?= ((int) ($message['contact_data_removed'] ?? 0)) > 0 ? ' · contact info erased' : '' ?></span>
                    </div>
                </div>
            <?php endforeach; ?>
        </div>
    </div>
</div>
<script>
    (function () {
        // Newest messages render first, so the log stays put at the top —
        // the entry area never drifts away from the player.
        var file = document.getElementById('wp-file');
        var name = document.getElementById('wp-filename');
        if (file && name) {
            file.addEventListener('change', function () {
                name.textContent = file.files.length ? '📎 ' + file.files[0].name : '📎 Attach image';
            });
        }
    })();
</script>

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
                <p style="margin:6px 0"><?php if ((int) $entry['year'] > 0): ?><span class="pill"><?= (int) $entry['year'] ?></span><?php endif; ?>
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
