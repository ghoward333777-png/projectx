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

// Background games: the couple's one shared game state, polled by both.
if ($userId !== null && (string) ($_GET['fragment'] ?? '') === 'game') {
    header('Content-Type: application/json');
    header('Cache-Control: private, no-store');
    try {
        echo json_encode($engine->watchGame($chatId, $userId));
    } catch (Throwable) {
        echo '{}';
    }
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
            case 'game':
                $gameState = json_decode((string) ($_POST['state'] ?? '{}'), true);
                $gameResult = $engine->setWatchGame(
                    (string) ($_POST['chat_id'] ?? ''),
                    $userId,
                    (string) ($_POST['game'] ?? ''),
                    is_array($gameState) ? $gameState : [],
                );
                if ($ajax) {
                    header('Content-Type: application/json');
                    echo json_encode($gameResult);
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
    /* Background games: a semi-transparent pop-up that floats over the
       page — play while watching and chatting, nothing pauses. */
    #wpg { position: fixed; top: 12%; right: 4%; width: 300px; z-index: 1000;
        background: rgba(10, 8, 16, .68); backdrop-filter: blur(9px); -webkit-backdrop-filter: blur(9px);
        border: 1px solid rgba(255, 156, 192, .35); border-radius: 14px; padding: 12px; color: #fff; }
    #wpg h3 { margin: 0; font-size: 14px; }
    #wpg .wpg-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px; }
    #wpg .wpg-top button, #wpg .wpg-menu button, #wpg .wpg-body button { margin: 0; padding: 5px 10px; font-size: 12px;
        border-radius: 8px; background: rgba(255, 255, 255, .14); color: #fff; }
    #wpg .wpg-menu { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
    #wpg .wpg-menu button { text-align: left; padding: 8px 10px; }
    #wpg .wpg-menu small { display: block; color: #c9bfd2; font-weight: 400; font-size: 10.5px; }
    #wpg .wpg-status { font-size: 12px; color: #ffc4da; margin: 6px 0; min-height: 15px; }
    #wpg .wpg-grid { display: grid; gap: 4px; }
    #wpg .wpg-cell { display: flex; align-items: center; justify-content: center; background: rgba(255, 255, 255, .09);
        border-radius: 7px; cursor: pointer; user-select: none; font-size: 22px; }
    #wpg .wpg-cell:hover { background: rgba(255, 255, 255, .18); }
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
        <?php if (($film['video_kind'] ?? '') === 'trailer'): ?>
            <span class="pill" style="background:#3a2a3e">official trailer — the full film isn't free on YouTube</span>
            <a href="https://www.youtube.com/results?search_query=<?= rawurlencode(trim((string) $film['title'] . ' ' . ((int) $film['year'] > 0 ? $film['year'] . ' ' : '') . 'full movie')) ?>"
               target="_blank" rel="noopener" style="color:#ffb8d2">Watch the full film on YouTube ↗</a>
        <?php endif; ?>
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
        // NO up-next queue on film embeds, EVER: when a main video
        // refuses to embed, YouTube silently plays the first queue item
        // instead — the "every pick shows the same movie" bug. A broken
        // embed now errors visibly and the fallback rotation handles it.
        $filmSrc = !empty($film['embed_url'])
            ? (string) $film['embed_url'] . '?rel=0&enablejsapi=1'
            : null;
        // Auto-rotate on failure: if the playing stream errors (a live
        // cam that went offline, an unavailable upload), the script
        // below swaps in the next playable entry from the same channel.
        $wpFallbacks = [];
        if (isset($film['channel'])) {
            foreach ($engine->channelLibrary((string) $film['channel'], '', 100)['films'] as $sibling) {
                if (!empty($sibling['embed_url']) && $sibling['id'] !== $film['id']) {
                    $wpFallbacks[] = [
                        'title' => (string) $sibling['title'],
                        'src' => (string) $sibling['embed_url'] . '?rel=0&enablejsapi=1&autoplay=1',
                    ];
                }
            }
        }
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

    <!-- Compact channel menu: pop-down submenus instead of a long row. -->
    <style>
        .chmenu { position: relative; display: inline-block; margin: 0 4px 0 0; }
        .chmenu summary { list-style: none; cursor: pointer; display: inline-block; background: #3a2a3e;
            color: #ffc4da; border-radius: 999px; padding: 6px 14px; font-size: 13px; font-weight: 700; }
        .chmenu summary::-webkit-details-marker { display: none; }
        .chmenu[open] summary { background: #ff9cc0; color: #2a0f1d; }
        .chmenu-list { position: absolute; top: calc(100% + 6px); left: 0; z-index: 40; min-width: 220px;
            background: #1d1824; border: 1px solid #574a61; border-radius: 12px; padding: 8px;
            display: flex; flex-direction: column; gap: 2px; box-shadow: 0 16px 32px rgba(0,0,0,.5); }
        .chmenu-list a { display: block; padding: 7px 10px; border-radius: 8px; color: #ffb8d2;
            text-decoration: none; font-size: 13px; margin: 0; }
        .chmenu-list a:hover { background: #262030; text-decoration: none; }
        .chmenu-list a.on { background: #4a2440; color: #ffd4e5; font-weight: 800; }
    </style>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <strong style="color:#eadff0;font-size:13px">Channels:</strong>
        <?php foreach (SlowDatingEngine::WATCH_CHANNEL_GROUPS as $groupLabel => $groupChannels): ?>
            <details class="chmenu"<?= $mode === 'library' && in_array($ch, $groupChannels, true) ? ' open' : '' ?>>
                <summary><?= sd_e($groupLabel) ?> ▾</summary>
                <div class="chmenu-list">
                    <?php foreach ($groupChannels as $slug): ?>
                        <a href="?chat=<?= sd_e($chatId) ?>&amp;ch=<?= sd_e($slug) ?>"<?= $mode === 'library' && $ch === $slug ? ' class="on"' : '' ?>><?= sd_e((string) $channels[$slug]['label']) ?></a>
                    <?php endforeach; ?>
                </div>
            </details>
        <?php endforeach; ?>
        <a href="?chat=<?= sd_e($chatId) ?>&amp;mode=premium" class="links" style="color:#ffb8d2;<?= $mode === 'premium' ? 'font-weight:800;text-decoration:underline' : '' ?>">Premium together</a>
        <a href="advanced-watch-party.php" style="color:#ffd97a">Advanced Watch Party →</a>
    </div>

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
            <button type="button" id="wpg-open" style="margin:0;padding:6px 14px;font-size:12.5px;background:#3a2a3e;color:#ffc4da">🎲 Games</button>
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
<!-- Background games pop-up: floats over player + chat, never pauses either. -->
<div id="wpg" hidden>
    <div class="wpg-top">
        <h3 id="wpg-title">🎲 Background games</h3>
        <div>
            <button type="button" id="wpg-menu-btn" title="All games">☰</button>
            <button type="button" id="wpg-close" title="Close">✕</button>
        </div>
    </div>
    <div class="wpg-status" id="wpg-status">Pick a game — you can keep chatting and watching.</div>
    <div id="wpg-body"></div>
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

        // Games adapter (live site): the couple's shared state on the chat.
        var WPG_ME = <?= json_encode($userId) ?>;
        var WPG_PARTNER = <?= json_encode($otherName) ?>;
        var WPG_PLAYERS = <?= json_encode(array_values((array) $chat['participants'])) ?>;
        var WPG_CHAT = <?= json_encode($chatId) ?>;
        function WPG_PUSH(game, state, ack) {
            var data = new FormData();
            data.append('action', 'game');
            data.append('ajax', '1');
            data.append('chat_id', WPG_CHAT);
            data.append('game', game);
            data.append('state', JSON.stringify(state));
            fetch('watch-party.php', { method: 'POST', body: data, credentials: 'same-origin' })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) { if (d && d.updated_at) { ack(d.updated_at); } })
                .catch(function () {});
        }
        function WPG_POLL(apply) {
            setInterval(function () {
                fetch('watch-party.php?fragment=game&chat=' + encodeURIComponent(WPG_CHAT), { credentials: 'same-origin' })
                    .then(function (r) { return r.ok ? r.json() : null; })
                    .then(apply)
                    .catch(function () {});
            }, 3500);
        }

        // ---- Background games: shared state on the chat, both players
        // poll it — the movie and the chat never pause for a move. ----
        (function () {
            var box = document.getElementById('wpg');
            if (!box) { return; }
            var me = WPG_ME;
            var partnerName = WPG_PARTNER;
            var players = WPG_PLAYERS;
            var chatRef = WPG_CHAT;
            var seat = Math.max(0, players.indexOf(me));
            var bodyEl = document.getElementById('wpg-body');
            var statusEl = document.getElementById('wpg-status');
            var titleEl = document.getElementById('wpg-title');
            var current = '';
            var state = null;
            var lastApplied = 0;
            function rng(seed) { return function () { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; }; }
            function shuffled(list, seed) {
                var copy = list.slice(); var r = rng(seed);
                for (var i = copy.length - 1; i > 0; i--) { var j = Math.floor(r() * (i + 1)); var t = copy[i]; copy[i] = copy[j]; copy[j] = t; }
                return copy;
            }
            var WYR = [['Travel the world for a year', 'Buy a home right now'], ['Always know the movie ending', 'Never see a spoiler again'],
                ['Dinner and dancing', 'Blanket fort and takeout'], ['Live by the ocean', 'Live in the mountains'],
                ['Re-live your best day', 'Preview one day of the future'], ['Only sunrise dates', 'Only midnight dates'],
                ['Sing everything you say', 'Dance everywhere you walk'], ['Cook together every night', 'Eat out every night'],
                ['A road trip with no map', 'A planned trip, every detail'], ['Love letters only', 'Voice notes only']];
            var TRIVIA = [['Which film says "You had me at hello"?', ['Jerry Maguire', 'Notting Hill', 'Ghost'], 0],
                ['Casablanca is set in which country?', ['Morocco', 'France', 'Egypt'], 0],
                ['In Titanic, Jack draws Rose wearing.', ['The Heart of the Ocean', 'A red scarf', 'A tiara'], 0],
                ['The Notebook couple are Noah and.', ['Allie', 'Emma', 'Rose'], 0],
                ['"To me, you are perfect" is from.', ['Love Actually', 'About Time', 'The Holiday'], 0],
                ['Audrey Hepburn stars in.', ['Charade', 'Pillow Talk', 'Gilda'], 0],
                ['Dirty Dancing: "Nobody puts ___ in a corner"', ['Baby', 'Frances', 'Penny'], 0],
                ['When Harry Met Sally ends on.', ['New Year\'s Eve', 'Valentine\'s Day', 'Christmas'], 0]];
            var BINGO_POOL = ['A kiss', 'Car chase', 'Plot twist', 'Sunset shot', 'Dance scene', 'Phone call', 'Rain scene', 'Flashback',
                'Wedding', 'Airport run', 'Slow motion', 'Tears', 'Big laugh', 'Song moment', 'A letter', '"I love you"'];
            var MEMO = ['❤️', '🌹', '🍷', '🎬', '🌙', '🎵', '☕', '💌'];
            var GAMES = {
                tictactoe: { name: 'Tic-Tac-Toe', tag: 'ultra-simple idle play',
                    init: function () { return { b: ['', '', '', '', '', '', '', '', ''], n: 0, over: '' }; } },
                connect4: { name: 'Connect Four', tag: 'drop tokens, four in a row',
                    init: function () { var b = []; for (var i = 0; i < 42; i++) { b.push(0); } return { b: b, n: 0, over: 0 }; } },
                memory: { name: 'Memory Match', tag: 'flip cards, find pairs',
                    init: function () { return { seed: Date.now() % 1000000, up: [], done: [], n: 0, score: [0, 0] }; } },
                wyr: { name: 'Would You Rather', tag: 'conversation cards',
                    init: function () { return { i: Math.floor(Math.random() * WYR.length), picks: {} }; } },
                trivia: { name: 'Trivia', tag: 'one easy question at a time',
                    init: function () { return { i: Math.floor(Math.random() * TRIVIA.length), picks: {} }; } },
                bingo: { name: 'Scene Bingo', tag: 'tap events as they happen',
                    init: function () { return { seed: Date.now() % 1000000, marks: {} }; } },
            };
            function turnOf(s) { return s.n % 2; }
            function myTurn(s) { return turnOf(s) === seat; }
            function escapeHtml(text) { var d = document.createElement('span'); d.textContent = String(text); return d.innerHTML; }
            function status(text) { statusEl.textContent = text; }
            function menu() {
                current = '';
                titleEl.textContent = '🎲 Background games';
                status('Pick a game - you can keep chatting and watching.');
                var html = '';
                for (var key in GAMES) {
                    html += '<button data-wpg-pick="' + key + '"><strong>' + GAMES[key].name + '</strong><small>' + GAMES[key].tag + '</small></button>';
                }
                bodyEl.innerHTML = '<div class="wpg-menu">' + html + '</div>';
            }
            function render() {
                if (!current || !state) { menu(); return; }
                titleEl.textContent = '🎲 ' + GAMES[current].name;
                var html = '';
                var i;
                if (current === 'tictactoe') {
                    var sym = ['X', 'O'];
                    html = '<div class="wpg-grid" style="grid-template-columns:repeat(3,1fr)">';
                    for (i = 0; i < 9; i++) { html += '<div class="wpg-cell" style="height:56px" data-wpg-m="' + i + '">' + (state.b[i] || '') + '</div>'; }
                    html += '</div>';
                    status(state.over ? (state.over === 'draw' ? 'Draw!' : state.over + ' wins!')
                        : (myTurn(state) ? 'Your move - you are ' + sym[seat] : partnerName + "'s move (" + sym[1 - seat] + ')'));
                } else if (current === 'connect4') {
                    html = '<div class="wpg-grid" style="grid-template-columns:repeat(7,1fr)">';
                    for (i = 0; i < 42; i++) {
                        var token = state.b[i] === 1 ? '🔴' : state.b[i] === 2 ? '🟡' : '';
                        html += '<div class="wpg-cell" style="height:32px;font-size:16px" data-wpg-m="' + (i % 7) + '">' + token + '</div>';
                    }
                    html += '</div>';
                    status(state.over ? (state.over === 3 ? 'Draw!' : (state.over === 1 ? 'Red' : 'Yellow') + ' wins!')
                        : (myTurn(state) ? 'Your drop - you are ' + (seat === 0 ? 'red' : 'yellow') : partnerName + "'s drop"));
                } else if (current === 'memory') {
                    var deck = shuffled(MEMO.concat(MEMO), state.seed);
                    html = '<div class="wpg-grid" style="grid-template-columns:repeat(4,1fr)">';
                    for (i = 0; i < 16; i++) {
                        var shown = state.done.indexOf(i) >= 0 || state.up.indexOf(i) >= 0;
                        html += '<div class="wpg-cell" style="height:44px" data-wpg-m="' + i + '">' + (shown ? deck[i] : '❔') + '</div>';
                    }
                    html += '</div>';
                    status('You ' + state.score[seat] + ' · ' + partnerName + ' ' + state.score[1 - seat]
                        + (state.done.length === 16 ? ' - finished!' : (myTurn(state) ? ' · your turn' : ' · their turn')));
                } else if (current === 'wyr') {
                    var pair = WYR[state.i % WYR.length];
                    var mine = state.picks[me];
                    html = '<p style="font-size:13px;margin:0 0 8px">Would you rather.</p>'
                        + '<button style="display:block;width:100%;margin-bottom:6px' + (mine === 0 ? ';background:#4a2440' : '') + '" data-wpg-m="0">' + escapeHtml(pair[0]) + '</button>'
                        + '<button style="display:block;width:100%' + (mine === 1 ? ';background:#4a2440' : '') + '" data-wpg-m="1">' + escapeHtml(pair[1]) + '</button>'
                        + '<button style="margin-top:8px" data-wpg-m="next">Next card →</button>';
                    var theirs = state.picks[players[1 - seat]];
                    status(mine === undefined ? 'Tap your pick - talk it out!'
                        : (theirs === undefined ? 'Waiting for ' + partnerName + '.'
                            : (mine === theirs ? 'Same pick - you two agree!' : 'Opposite picks - discuss!')));
                } else if (current === 'trivia') {
                    var q = TRIVIA[state.i % TRIVIA.length];
                    var picked = state.picks[me];
                    html = '<p style="font-size:13px;margin:0 0 8px">' + escapeHtml(q[0]) + '</p>';
                    for (i = 0; i < q[1].length; i++) {
                        var mark = picked !== undefined ? (i === q[2] ? ' ✓' : (i === picked ? ' ✗' : '')) : '';
                        html += '<button style="display:block;width:100%;margin-bottom:6px' + (picked !== undefined && i === q[2] ? ';background:#17351f' : '') + '" data-wpg-m="' + i + '">' + escapeHtml(q[1][i]) + mark + '</button>';
                    }
                    html += '<button style="margin-top:4px" data-wpg-m="next">Next question →</button>';
                    status(picked === undefined ? 'No pressure - one question at a time.' : (picked === q[2] ? 'Right!' : 'The answer: ' + q[1][q[2]]));
                } else if (current === 'bingo') {
                    var card = shuffled(BINGO_POOL, state.seed + seat * 7919);
                    var marks = state.marks[me] || [];
                    html = '<div class="wpg-grid" style="grid-template-columns:repeat(4,1fr)">';
                    for (i = 0; i < 16; i++) {
                        html += '<div class="wpg-cell" style="height:44px;font-size:9.5px;text-align:center;padding:2px'
                            + (marks.indexOf(i) >= 0 ? ';background:#4a2440' : '') + '" data-wpg-m="' + i + '">' + escapeHtml(card[i]) + '</div>';
                    }
                    html += '</div>';
                    var lines = [[0,1,2,3],[4,5,6,7],[8,9,10,11],[12,13,14,15],[0,4,8,12],[1,5,9,13],[2,6,10,14],[3,7,11,15],[0,5,10,15],[3,6,9,12]];
                    var bingo = lines.some(function (line) { return line.every(function (cell) { return marks.indexOf(cell) >= 0; }); });
                    var theirMarks = (state.marks[players[1 - seat]] || []).length;
                    status(bingo ? 'BINGO! Tell ' + partnerName + '!' : 'Tap events as they happen · ' + partnerName + ' has ' + theirMarks + ' marked');
                }
                bodyEl.innerHTML = html + '<p style="margin:8px 0 0"><button data-wpg-reset="1">↺ New round</button></p>';
            }
            function push() { WPG_PUSH(current, state, function (at) { lastApplied = at; }); }
            function ticWin(b) {
                var wins = [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]];
                for (var w = 0; w < wins.length; w++) {
                    var a = wins[w];
                    if (b[a[0]] && b[a[0]] === b[a[1]] && b[a[0]] === b[a[2]]) { return b[a[0]]; }
                }
                return b.every(function (cell) { return cell; }) ? 'draw' : '';
            }
            function c4Win(b, who) {
                for (var r = 0; r < 6; r++) {
                    for (var c = 0; c < 7; c++) {
                        var dirs = [[0, 1], [1, 0], [1, 1], [1, -1]];
                        for (var d = 0; d < 4; d++) {
                            var hit = 0;
                            for (var k = 0; k < 4; k++) {
                                var rr = r + dirs[d][0] * k, cc = c + dirs[d][1] * k;
                                if (rr >= 0 && rr < 6 && cc >= 0 && cc < 7 && b[rr * 7 + cc] === who) { hit++; }
                            }
                            if (hit === 4) { return true; }
                        }
                    }
                }
                return false;
            }
            function move(action) {
                if (!current || !state) { return; }
                var i;
                if (current === 'tictactoe') {
                    i = +action;
                    if (state.over || state.b[i] || !myTurn(state)) { return; }
                    state.b[i] = seat === 0 ? 'X' : 'O';
                    state.n++;
                    state.over = ticWin(state.b);
                } else if (current === 'connect4') {
                    if (state.over || !myTurn(state)) { return; }
                    var col = +action, row = -1;
                    for (i = 5; i >= 0; i--) { if (!state.b[i * 7 + col]) { row = i; break; } }
                    if (row < 0) { return; }
                    var who = seat + 1;
                    state.b[row * 7 + col] = who;
                    state.n++;
                    if (c4Win(state.b, who)) { state.over = who; } else if (state.n === 42) { state.over = 3; }
                } else if (current === 'memory') {
                    i = +action;
                    if (!myTurn(state) || state.done.indexOf(i) >= 0 || state.up.indexOf(i) >= 0 || state.up.length === 2) { return; }
                    state.up.push(i);
                    if (state.up.length === 2) {
                        var deck = shuffled(MEMO.concat(MEMO), state.seed);
                        var a = state.up[0], b = state.up[1];
                        if (deck[a] === deck[b]) {
                            state.done.push(a, b); state.score[seat]++; state.up = [];
                        } else {
                            render(); push();
                            setTimeout(function () { state.up = []; state.n++; render(); push(); }, 1100);
                            return;
                        }
                    }
                } else if (current === 'wyr') {
                    if (action === 'next') { state = { i: (state.i + 1) % WYR.length, picks: {} }; }
                    else { state.picks[me] = +action; }
                } else if (current === 'trivia') {
                    if (action === 'next') { state = { i: (state.i + 1) % TRIVIA.length, picks: {} }; }
                    else if (state.picks[me] === undefined) { state.picks[me] = +action; }
                } else if (current === 'bingo') {
                    i = +action;
                    var marks = state.marks[me] || [];
                    var at = marks.indexOf(i);
                    if (at >= 0) { marks.splice(at, 1); } else { marks.push(i); }
                    state.marks[me] = marks;
                }
                render();
                push();
            }
            document.getElementById('wpg-open').addEventListener('click', function () { box.hidden = false; if (!current) { menu(); } });
            document.getElementById('wpg-close').addEventListener('click', function () { box.hidden = true; });
            document.getElementById('wpg-menu-btn').addEventListener('click', menu);
            box.addEventListener('click', function (event) {
                var pick = event.target.closest('[data-wpg-pick]');
                if (pick) { current = pick.getAttribute('data-wpg-pick'); state = GAMES[current].init(); render(); push(); return; }
                var reset = event.target.closest('[data-wpg-reset]');
                if (reset) { state = GAMES[current].init(); render(); push(); return; }
                var action = event.target.closest('[data-wpg-m]');
                if (action) { move(action.getAttribute('data-wpg-m')); }
            });
            WPG_POLL(function (d) {
                if (!d || !d.updated_at || d.updated_at <= lastApplied || d.set_by === me) { return; }
                lastApplied = d.updated_at;
                current = d.game;
                state = d.state;
                if (!box.hidden) { render(); }
                else if (d.game) { box.hidden = false; render(); }
            });
            window.WPG_TEST = { open: function () { box.hidden = false; menu(); }, pick: function (k) { current = k; state = GAMES[k].init(); render(); }, move: move, get: function () { return { current: current, state: state, seat: seat }; } };
        })();

        // ---- Playlist slot control. YouTube ignores index= on playlist
        // embeds, so slots are reached by commanding the RUNNING player
        // with playVideoAt — never by reloading the iframe. ----
        var player = document.getElementById('wp-player');
        var plIndex = -1;
        // Auto-rotate on failure: a dead live cam or unavailable upload
        // reports onError through the player API; the page then swaps in
        // the next playable entry from the same channel.
        var wpFallbacks = <?= json_encode($wpFallbacks ?? []) ?>;
        var wpFallbackAt = 0;
        var wpLastAdvance = 0;
        function wpSubscribe() {
            [900, 1800, 3200].forEach(function (delay) {
                setTimeout(function () {
                    if (player && player.contentWindow) {
                        player.contentWindow.postMessage(JSON.stringify({ event: 'listening', id: 'wp' }), '*');
                    }
                }, delay);
            });
        }
        wpSubscribe();
        function wpAdvance(code) {
            var now = Date.now();
            if (!player || wpFallbacks.length === 0 || wpFallbackAt >= wpFallbacks.length || now - wpLastAdvance < 400) { return; }
            wpLastAdvance = now;
            var next = wpFallbacks[wpFallbackAt++];
            player.src = next.src;
            wpSubscribe();
            var pill = document.querySelector('#watchparty .chat-header span');
            if (pill) { pill.textContent = '⚠ Stream failed (error ' + code + ') — rotated to: ' + next.title; }
        }
        window.addEventListener('message', function (event) {
            try {
                var data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
                if (data && data.info && typeof data.info.playlistIndex === 'number') { plIndex = data.info.playlistIndex; }
                if (data && data.event === 'onError') { wpAdvance(Number(data.info)); }
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
