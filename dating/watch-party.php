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

/**
 * The chat log as an HTML fragment (newest first). Sending and polling
 * both swap ONLY this fragment into the page over fetch(), so the video
 * player is never reloaded — the movie keeps playing while the couple
 * talks.
 */
function wp_messages_html(SlowDatingEngine $engine, string $chatId, string $userId): string
{
    $chat = $engine->store()->get('chats', $chatId);
    if ($chat === null || !in_array($userId, (array) $chat['participants'], true)) {
        return '';
    }
    $otherId = '';
    foreach ((array) $chat['participants'] as $participant) {
        if ($participant !== $userId) {
            $otherId = (string) $participant;
        }
    }
    $otherName = (string) ($engine->profile($otherId)['display_name'] ?: $otherId);
    $html = '';
    foreach (array_reverse((array) $chat['messages']) as $message) {
        $html .= '<div class="message' . ($message['sender_id'] === $userId ? ' me' : '') . '">';
        if (isset($message['image'])) {
            $html .= '<div class="message-images"><img src="chatimage.php?chat=' . urlencode($chatId)
                . '&amp;m=' . urlencode((string) $message['message_id']) . '" alt="Shared image"></div>';
        }
        if ((string) $message['text'] !== '') {
            $html .= '<span>' . sd_e((string) $message['text']) . '</span>';
        }
        $html .= '<div class="message-meta"><span>' . ($message['sender_id'] === $userId ? 'You' : sd_e($otherName)) . '</span>'
            . '<span>' . sd_e(gmdate('M j, H:i', (int) $message['sent_at']))
            . (((int) ($message['contact_data_removed'] ?? 0)) > 0 ? ' · contact info erased' : '') . '</span></div></div>';
    }
    return $html;
}

// Polling endpoint: just the chat fragment, no page, no player reload.
if ($userId !== null && (string) ($_GET['fragment'] ?? '') === 'messages') {
    header('Content-Type: text/html; charset=utf-8');
    header('Cache-Control: private, no-store');
    echo wp_messages_html($engine, $chatId, $userId);
    exit;
}

// Premium rooms: the shared timecode authority, polled by both players.
if ($userId !== null && (string) ($_GET['fragment'] ?? '') === 'sync') {
    header('Content-Type: application/json');
    header('Cache-Control: private, no-store');
    try {
        echo json_encode($engine->watchSync($chatId, $userId));
    } catch (Throwable) {
        echo '{}';
    }
    exit;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && $userId !== null) {
    $ajax = isset($_POST['ajax']);
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
                if ($ajax) {
                    // Sent over fetch(): return the fresh chat fragment only.
                    // The page — and the movie — stay exactly where they are.
                    header('Content-Type: text/html; charset=utf-8');
                    header('Cache-Control: private, no-store');
                    echo wp_messages_html($engine, (string) ($_POST['chat_id'] ?? ''), $userId);
                    exit;
                }
                break;
            case 'sync':
                $sync = $engine->setWatchSync((string) ($_POST['chat_id'] ?? ''), $userId, [
                    'video' => (string) ($_POST['video'] ?? ''),
                    'position' => (float) ($_POST['position'] ?? 0),
                    'playing' => ($_POST['playing'] ?? '') === '1',
                ]);
                if ($ajax) {
                    header('Content-Type: application/json');
                    echo json_encode($sync);
                    exit;
                }
                $notice = 'Shared controls updated for both of you.';
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
        if ($ajax) {
            http_response_code(422);
            header('Content-Type: text/plain; charset=utf-8');
            echo $exception->getMessage();
            exit;
        }
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
$channels = $engine->watchChannels();
$ch = (string) ($_GET['ch'] ?? 'romance');
if (!isset($channels[$ch])) {
    $ch = 'romance';
}
$library = $engine->channelLibrary($ch, $q, $perPage, $page * $perPage);
$mode = (string) ($_GET['mode'] ?? 'library');
if (!in_array($mode, ['library', 'premium'], true)) {
    $mode = 'library';
}
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
        <span class="pill" style="margin-left:8px"><?= sd_e((string) $film['title']) ?> ·
            <?= (int) $film['rank'] > 0
                ? '#' . (int) $film['rank'] . ' in the playlist'
                : sd_e((string) ($channels[(string) ($film['channel'] ?? 'romance')]['label'] ?? 'channel pick')) . (!empty($film['live']) ? ' · ● LIVE' : '')
            ?><?= $party['custom_pick'] ? ' · your pick' : ' · tonight\'s schedule' ?></span>
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
        <?php
        // Picking from the library must ALWAYS change the video. A film
        // the couple picked wins the player when it has its own stream;
        // a pick without one plays the operator playlist at that film's
        // slot; with no pick the admin-pasted embed (or the daily film)
        // plays. enablejsapi lets the Premium room's shared controls
        // drive the player without ever reloading it.
        $override = $engine->watchPartyEmbed();
        $overrideSrc = $override !== null
            ? $override . (str_contains($override, '?') ? '&' : '?') . 'enablejsapi=1'
            : null;
        // The up-next playlist rides along ONLY on curated, verified
        // films. On a search-resolved id it must never be attached:
        // when a main video refuses to embed, YouTube silently plays
        // the FIRST playlist item instead — the "every pick shows the
        // same movie" bug. A broken resolved id now shows YouTube's
        // own error, honestly, and the couple picks something else.
        $curated = !empty($film['youtube_id']) && !isset($film['channel']);
        $filmSrc = !empty($film['embed_url'])
            ? (string) $film['embed_url'] . '?rel=0&enablejsapi=1'
                . ($curated && $party['playlist'] !== [] ? '&playlist=' . implode(',', $party['playlist']) : '')
            : null;
        // NOTE: YouTube IGNORES the index= URL parameter on playlist
        // embeds — the only way to land on a slot is the player API's
        // playVideoAt command, sent by the script below ($wpSlot).
        $wpSlot = null;
        if ($party['custom_pick'] && $filmSrc !== null) {
            $embedSrc = $filmSrc;
        } elseif ($party['custom_pick'] && $overrideSrc !== null) {
            $embedSrc = $overrideSrc . '&autoplay=1';
            $wpSlot = (int) $film['rank'] % 60;
        } else {
            $embedSrc = $overrideSrc ?? $filmSrc;
        }
        ?>
        <?php if ($embedSrc !== null): ?>
            <iframe id="wp-player" src="<?= sd_e($embedSrc) ?>" title="<?= sd_e((string) $film['title']) ?>"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowfullscreen></iframe>
        <?php else: ?>
            <div class="video-fallback">
                <strong style="color:#fff;font-size:18px"><?= sd_e($filmLabel) ?></strong>
                <span style="color:#9ca3af;font-size:13px;max-width:48ch">Finding this film's stream — refresh in a moment.</span>
            </div>
        <?php endif; ?>
    </div>

    <?php if ($overrideSrc !== null): ?>
    <!-- Local playlist rotation: swaps the player's source in place —
         no page load, no round-trip. -->
    <p style="margin:0;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <span style="color:#9ca3af;font-size:12.5px">Rotate the playlist:</span>
        <button type="button" class="quiet" data-wprot="-1" style="margin:0;padding:6px 12px;font-size:12px">⏮ Previous</button>
        <button type="button" class="quiet" data-wprot="1" style="margin:0;padding:6px 12px;font-size:12px">Next ⏭</button>
        <button type="button" class="quiet" data-wprot="r" style="margin:0;padding:6px 12px;font-size:12px">🔀 Shuffle</button>
    </p>
    <?php endif; ?>

    <p class="links" style="margin:0">
        <strong style="color:#eadff0;font-size:13px">Channels:</strong>
        <?php foreach ($channels as $slug => $meta): ?>
            <a href="?chat=<?= sd_e($chatId) ?>&amp;ch=<?= sd_e($slug) ?>"<?= $mode === 'library' && $ch === $slug ? ' style="font-weight:800;text-decoration:underline"' : '' ?>><?= sd_e((string) $meta['label']) ?></a>
        <?php endforeach; ?>
        <a href="?chat=<?= sd_e($chatId) ?>&amp;mode=premium"<?= $mode === 'premium' ? ' style="font-weight:800;text-decoration:underline"' : '' ?>>Premium together · bring your own YouTube</a>
        <a href="advanced-watch-party.php" style="color:#ffd97a">Advanced Watch Party · rooms &amp; split payments →</a>
    </p>

    <?php if ($mode === 'premium'): ?>
    <?php $sync = $engine->watchSync($chatId, $userId); ?>
    <section style="margin-top:0">
        <h2>Premium together — Bring-Your-Own-YouTube-Account Sync</h2>
        <p style="margin:0 0 10px">The same model Teleparty uses: <strong style="color:#f3eef6">1.</strong> You and
            <?= sd_e($otherName) ?> are in this watch-party room. <strong style="color:#f3eef6">2.</strong> Each of
            you is signed into your own YouTube account in the embedded player above — YouTube Premium plays
            ad-free on your own subscription. <strong style="color:#f3eef6">3.</strong> SlowDating keeps the two
            players in lock-step with a shared timecode authority (live sync channel).
            <strong style="color:#f3eef6">4.</strong> Chat, reactions, and the shared controls below live on this
            page. <strong style="color:#f3eef6">5.</strong> Your membership pays for the sync service —
            <em>never for the movie</em>.</p>
        <div class="card" style="margin-bottom:12px">
            <strong>Shared controls · timecode authority</strong>
            <p id="wp-sync-state" style="margin:6px 0;font-size:13px;color:#a294ad"><?php
                if ((string) $sync['video'] !== '') {
                    echo 'Now syncing: <strong style="color:#f3eef6">' . sd_e((string) $sync['video']) . '</strong> · '
                        . ($sync['playing'] ? 'playing' : 'paused') . ' at ' . gmdate('H:i:s', (int) $sync['position']);
                } else {
                    echo 'Room open — pick a film below, or press Play together.';
                }
            ?></p>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
                <button type="button" class="send-btn" id="wp-sync-play" style="padding:8px 14px">▶ Play together</button>
                <button type="button" class="quiet" id="wp-sync-pause" style="margin:0;padding:8px 14px;font-size:13px">⏸ Pause both</button>
                <button type="button" class="quiet" id="wp-sync-re" style="margin:0;padding:8px 14px;font-size:13px">⟲ Re-sync <?= sd_e($otherName) ?></button>
            </div>
        </div>
        <h3 style="margin:0 0 6px">Romantic comedies on Premium</h3>
        <p style="margin:0 0 10px;font-size:12.5px;color:#a294ad">A curated rom-com playlist for Premium rooms.
            Each of you streams on your own account — availability varies by region.</p>
        <div class="grid">
            <?php foreach ($engine->premiumRomcoms() as $romcom): ?>
                <div class="card">
                    <strong><?= sd_e((string) $romcom['title']) ?></strong> <span class="pill"><?= (int) $romcom['year'] ?></span>
                    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
                        <button type="button" class="send-btn" style="padding:7px 12px;font-size:12px"
                                data-wpsyncfilm="<?= sd_e((string) $romcom['title'] . ' (' . $romcom['year'] . ')') ?>">Watch together</button>
                        <a href="<?= sd_e((string) $romcom['watch_url']) ?>" target="_blank" rel="noopener"
                           style="color:#ffb8d2;font-size:12px;align-self:center">Open on YouTube ↗</a>
                    </div>
                </div>
            <?php endforeach; ?>
        </div>
    </section>
    <?php endif; ?>

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
            <span class="hint" id="wp-flash" style="color:#ff9cba"></span>
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

        // THE RULE: the movie never pauses because chat is happening.
        // Sending goes over fetch() and swaps only the chat log; the
        // player iframe is never touched. Without JS the form still
        // posts the old way as a fallback.
        var form = document.querySelector('#watchparty .input-area');
        var log = document.getElementById('wp-messages');
        var flash = document.getElementById('wp-flash');
        var fragmentUrl = 'watch-party.php?fragment=messages&chat=<?= urlencode($chatId) ?>';
        if (form && log) {
            var textarea = form.querySelector('textarea[name=text]');
            if (textarea) {
                textarea.addEventListener('keydown', function (event) {
                    if (event.key === 'Enter' && !event.shiftKey) {
                        event.preventDefault();
                        if (form.requestSubmit) { form.requestSubmit(); }
                    }
                });
            }
            form.addEventListener('submit', function (event) {
                event.preventDefault();
                var data = new FormData(form);
                data.append('ajax', '1');
                var button = form.querySelector('.send-btn');
                if (button) { button.disabled = true; }
                fetch('watch-party.php', { method: 'POST', body: data, credentials: 'same-origin' })
                    .then(function (response) {
                        return response.text().then(function (body) {
                            if (!response.ok) { throw new Error(body || 'Could not send the message.'); }
                            log.innerHTML = body;
                            form.querySelector('textarea[name=text]').value = '';
                            if (file) { file.value = ''; }
                            if (name) { name.textContent = '📎 Attach image'; }
                            if (flash) { flash.textContent = ''; }
                        });
                    })
                    .catch(function (problem) {
                        if (flash) { flash.textContent = problem.message; }
                    })
                    .then(function () {
                        if (button) { button.disabled = false; }
                    });
            });

            // Poll for the partner's messages while the movie plays.
            setInterval(function () {
                fetch(fragmentUrl, { credentials: 'same-origin' })
                    .then(function (response) { return response.ok ? response.text() : null; })
                    .then(function (body) {
                        if (body !== null && body !== log.innerHTML) { log.innerHTML = body; }
                    })
                    .catch(function () { /* transient network hiccup — the next poll retries */ });
            }, 7000);
        }

        // ---- Playlist slot control. YouTube ignores index= on playlist
        // embeds, so slots are reached by commanding the RUNNING player
        // with playVideoAt — never by reloading the iframe. ----
        var player = document.getElementById('wp-player');
        var plIndex = -1;
        window.addEventListener('message', function (event) {
            try {
                var data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
                if (data && data.info && typeof data.info.playlistIndex === 'number') { plIndex = data.info.playlistIndex; }
            } catch (ignored) {}
        });
        function wpPlaySlot(slot) {
            var tries = 0;
            var timer = setInterval(function () {
                if (!player || plIndex === slot || tries++ > 10) { clearInterval(timer); return; }
                if (player.contentWindow) {
                    player.contentWindow.postMessage(JSON.stringify({ event: 'listening', id: 'wp' }), '*');
                    player.contentWindow.postMessage(JSON.stringify({ event: 'command', func: 'playVideoAt', args: [slot] }), '*');
                }
            }, 700);
        }
        var wpSlot = <?= json_encode($wpSlot) ?>;
        if (wpSlot !== null) { wpPlaySlot(wpSlot); }
        var rotIndex = <?= $wpSlot !== null ? $wpSlot : 0 ?>;
        document.querySelectorAll('button[data-wprot]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var step = btn.getAttribute('data-wprot');
                rotIndex = step === 'r' ? Math.floor(Math.random() * 60) : (rotIndex + parseInt(step, 10) + 60) % 60;
                wpPlaySlot(rotIndex);
            });
        });

        // ---- Premium room: the shared timecode authority. Commands go
        // to the player over the YouTube iframe API — never a reload. ----
        var premium = <?= json_encode($mode === 'premium') ?>;
        if (premium && player) {
            var chatIdJs = <?= json_encode($chatId) ?>;
            var lastTime = 0;
            var lastApplied = <?= $mode === 'premium' ? (int) ($sync['updated_at'] ?? 0) : 0 ?>;
            var currentVideo = <?= json_encode($mode === 'premium' ? (string) $sync['video'] : '') ?>;
            var stateLine = document.getElementById('wp-sync-state');
            function ytCmd(func, args) {
                if (player.contentWindow) {
                    player.contentWindow.postMessage(JSON.stringify({ event: 'command', func: func, args: args || [] }), '*');
                }
            }
            window.addEventListener('message', function (event) {
                try {
                    var data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
                    if (data && data.info && typeof data.info.currentTime === 'number') { lastTime = data.info.currentTime; }
                } catch (ignored) {}
            });
            setTimeout(function () {
                if (player.contentWindow) {
                    player.contentWindow.postMessage(JSON.stringify({ event: 'listening', id: 'wp' }), '*');
                }
            }, 1500);
            function clock(seconds) {
                seconds = Math.max(0, Math.floor(seconds));
                return String(Math.floor(seconds / 3600)).padStart(2, '0') + ':'
                    + String(Math.floor(seconds / 60) % 60).padStart(2, '0') + ':'
                    + String(seconds % 60).padStart(2, '0');
            }
            function applySync(state) {
                if (!state || !state.updated_at || state.updated_at <= lastApplied) { return; }
                lastApplied = state.updated_at;
                if (state.video) { currentVideo = state.video; }
                if (stateLine) {
                    stateLine.textContent = currentVideo
                        ? 'Now syncing: ' + currentVideo + ' · ' + (state.playing ? 'playing' : 'paused') + ' at ' + clock(state.position || 0)
                        : 'Shared controls active · ' + (state.playing ? 'playing' : 'paused') + ' at ' + clock(state.position || 0);
                }
                ytCmd('seekTo', [state.position || 0, true]);
                ytCmd(state.playing ? 'playVideo' : 'pauseVideo');
            }
            function pushSync(playing, video) {
                var data = new FormData();
                data.append('action', 'sync');
                data.append('ajax', '1');
                data.append('chat_id', chatIdJs);
                data.append('playing', playing ? '1' : '0');
                data.append('position', String(Math.floor(lastTime)));
                data.append('video', video || currentVideo);
                fetch('watch-party.php', { method: 'POST', body: data, credentials: 'same-origin' })
                    .then(function (response) { return response.ok ? response.json() : null; })
                    .then(applySync)
                    .catch(function () {});
            }
            var syncPlay = document.getElementById('wp-sync-play');
            var syncPause = document.getElementById('wp-sync-pause');
            var syncRe = document.getElementById('wp-sync-re');
            if (syncPlay) { syncPlay.addEventListener('click', function () { ytCmd('playVideo'); pushSync(true); }); }
            if (syncPause) { syncPause.addEventListener('click', function () { ytCmd('pauseVideo'); pushSync(false); }); }
            if (syncRe) { syncRe.addEventListener('click', function () { pushSync(true); }); }
            document.querySelectorAll('button[data-wpsyncfilm]').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    pushSync(false, btn.getAttribute('data-wpsyncfilm'));
                    window.scrollTo({ top: 0, behavior: 'smooth' });
                });
            });
            // Both players follow the timecode authority.
            setInterval(function () {
                fetch('watch-party.php?fragment=sync&chat=' + encodeURIComponent(chatIdJs), { credentials: 'same-origin' })
                    .then(function (response) { return response.ok ? response.json() : null; })
                    .then(applySync)
                    .catch(function () {});
            }, 4000);
        }
    })();
</script>

<?php if ($mode === 'library'): ?>
<section>
    <h2><?= sd_e((string) $channels[$ch]['label']) ?> — the showcase</h2>
    <p><?= sd_e((string) $channels[$ch]['blurb']) ?>
        <?= $ch === 'romance' ? ' Tonight\'s schedule picks one for everyone; your watch party can swap to any of them.'
            : ' Pick anything here and it plays in your watch party player, chat right below.' ?></p>
    <form method="get" style="background:none;border:0;padding:0;margin:0 0 12px">
        <input type="hidden" name="chat" value="<?= sd_e($chatId) ?>">
        <input type="hidden" name="ch" value="<?= sd_e($ch) ?>">
        <label>Search this channel<?= $ch === 'romance' ? ' (title, year, or era — e.g. "jazz", "1999", "golden age")' : ' (title or scene — e.g. "waterfall", "harbor", "psalms")' ?></label>
        <input name="q" value="<?= sd_e($q) ?>" placeholder="<?= $ch === 'romance' ? 'The Notebook' : ($ch === 'nature' ? 'waterfall' : 'search…') ?>">
        <button type="submit">Search</button>
    </form>
    <p style="margin:0 0 8px;font-size:13px"><?= (int) $library['total'] ?> title<?= $library['total'] === 1 ? '' : 's' ?><?= $q !== '' ? ' matching "' . sd_e($q) . '"' : ' in this channel' ?> · page <?= $page + 1 ?></p>
    <div class="grid">
        <?php foreach ($library['films'] as $entry): ?>
            <div class="card">
                <strong><?= (int) $entry['rank'] > 0 ? '#' . (int) $entry['rank'] . ' · ' : '' ?><?= sd_e((string) $entry['title']) ?></strong>
                <p style="margin:6px 0"><?php if ((int) $entry['year'] > 0): ?><span class="pill"><?= (int) $entry['year'] ?></span><?php endif; ?>
                    <span class="pill"><?= sd_e((string) $entry['tag']) ?></span>
                    <?php if (!empty($entry['live'])): ?><span class="pill" style="background:#3c1f32;color:#ff9cba">● LIVE</span><?php endif; ?>
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
        <?php if ($page > 0): ?><a href="?chat=<?= sd_e($chatId) ?>&amp;ch=<?= sd_e($ch) ?>&amp;q=<?= sd_e($q) ?>&amp;p=<?= $page - 1 ?>">&#8249; Previous page</a><?php endif; ?>
        <?php if (($page + 1) * $perPage < (int) $library['total']): ?><a href="?chat=<?= sd_e($chatId) ?>&amp;ch=<?= sd_e($ch) ?>&amp;q=<?= sd_e($q) ?>&amp;p=<?= $page + 1 ?>">Next page &#8250;</a><?php endif; ?>
    </p>
</section>
<?php endif; ?>

<?php sd_page_close();
