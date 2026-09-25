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

// ---- Watch Room (video-chat-player): the module that IS the player now.
// One persistent room per couple: synced playback plus video chat in a
// single frame, driven natively through the module's PHP library. The
// showcase and the playlist logic feed the room.
require_once __DIR__ . '/video-chat-player/lib/WatchRoomApi.php';

/** The module's API bound to its own rooms/media folders. */
function wp_room_api(): WatchRoomApi
{
    static $api = null;
    if ($api === null) {
        $config = require __DIR__ . '/video-chat-player/config.php';
        $api = new WatchRoomApi(new RoomStore((string) $config['rooms_dir']), (string) $config['media_dir'], true, $config);
    }
    return $api;
}

/** A film's playable URL for the room (verified stream or trailer id). */
function wp_film_url(array $film): ?string
{
    $id = (string) ($film['youtube_id'] ?? '');
    return $id !== '' ? 'https://www.youtube.com/watch?v=' . $id : null;
}

/**
 * The couple's Watch Room: created on first visit (first item = the
 * current film, else the admin playlist), rejoined on later loads, and
 * remembered on the chat record. Returns id, member id, host token.
 */
function wp_watch_room(SlowDatingEngine $engine, string $chatId, string $userId, string $myName, ?array $film, ?string $override): ?array
{
    $api = wp_room_api();
    $chat = $engine->store()->get('chats', $chatId);
    if ($chat === null || !in_array($userId, (array) $chat['participants'], true)) {
        return null;
    }
    $info = (array) ($chat['watch_room'] ?? []);
    $roomId = (string) ($info['id'] ?? '');
    $room = $roomId !== '' ? $api->rooms()->load($roomId) : null;
    if ($room === null) {
        // First visit (or the old room expired): open a fresh room seeded
        // with the couple's current film, else the operator's playlist.
        $src = ($film !== null ? wp_film_url($film) : null) ?? ($override ?? '');
        [$status, $payload] = $api->handle('room.create', 'POST', ['name' => 'Watch Party', 'src' => $src]);
        if ($status !== 200) {
            return null;
        }
        $info = [
            'id' => (string) $payload['room']['id'],
            'host_token' => (string) $payload['hostToken'],
            'members' => [$userId => (string) $payload['memberId']],
        ];
        $chat['watch_room'] = $info;
        $engine->store()->put('chats', $chatId, $chat);
        return ['id' => $info['id'], 'member' => (string) $payload['memberId'], 'host_token' => $info['host_token']];
    }
    $memberId = (string) (((array) ($info['members'] ?? []))[$userId] ?? '');
    if ($memberId === '' || !isset($room['members'][$memberId])) {
        [$status, $payload] = $api->handle('room.join', 'POST', ['roomId' => $roomId, 'name' => $myName]);
        if ($status !== 200) {
            return null;
        }
        $memberId = (string) $payload['memberId'];
        $info['members'][$userId] = $memberId;
        $chat['watch_room'] = $info;
        $engine->store()->put('chats', $chatId, $chat);
    }
    return ['id' => $roomId, 'member' => $memberId, 'host_token' => (string) ($info['host_token'] ?? '')];
}

/**
 * A pick from the showcase lands in the room for BOTH viewers: reuse the
 * film's existing playlist item when it is already there, else add it,
 * then jump the shared playback to it.
 */
function wp_room_play(SlowDatingEngine $engine, string $chatId, string $userId, string $myName, array $film): void
{
    $url = wp_film_url($film);
    if ($url === null) {
        return;   // no verified stream — the room keeps its current item
    }
    $roomInfo = wp_watch_room($engine, $chatId, $userId, $myName, $film, null);
    if ($roomInfo === null) {
        return;
    }
    $api = wp_room_api();
    $itemId = null;
    [$status, $payload] = $api->handle('playlist.get', 'GET', ['roomId' => $roomInfo['id'], 'memberId' => $roomInfo['member']]);
    if ($status === 200) {
        foreach ((array) ($payload['playlist']['items'] ?? []) as $item) {
            // A YouTube item's src IS the 11-character video id.
            if (($item['kind'] ?? '') === 'youtube' && (string) ($item['src'] ?? '') === (string) $film['youtube_id']) {
                $itemId = (string) $item['id'];
                break;
            }
        }
    }
    if ($itemId === null) {
        [$status, $payload] = $api->handle('playlist.add', 'POST', ['roomId' => $roomInfo['id'], 'memberId' => $roomInfo['member'], 'url' => $url]);
        if ($status !== 200 || !isset($payload['item']['id'])) {
            return;
        }
        $itemId = (string) $payload['item']['id'];
    }
    $api->handle('state.set', 'POST', [
        'roomId' => $roomInfo['id'],
        'memberId' => $roomInfo['member'],
        'hostToken' => $roomInfo['host_token'],
        'state' => ['itemId' => $itemId, 'playing' => true, 'mediaTime' => 0],
    ]);
}

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
                // The pick lands in the couple's Watch Room playlist and the
                // shared playback jumps to it — for both viewers at once.
                wp_room_play(
                    $engine,
                    (string) ($_POST['chat_id'] ?? ''),
                    $userId,
                    (string) ($engine->profile($userId)['display_name'] ?: 'Member'),
                    (array) $party['film'],
                );
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

sd_page_open('Watch Party', 'SlowMoDating.com · a movie date, right here');
?>
<style>
    /* Player + chat, one column — the Watch Party layout. */
    #watchparty { display: flex; flex-direction: column; gap: 16px; }
    /* The Watch Room frame: the module's synced player + video chat.
       Sized so the whole frame AND the showcase entry stay on screen. */
    #watchparty .wp-room { display: block; border: 1px solid #1f2937; border-radius: 12px; width: 100%;
        aspect-ratio: 16 / 9; background: #020617; box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
        max-width: min(100%, calc((100vh - 240px) * 1.7778)); margin: 0 auto; }
    #watchparty .video-wrapper {
        position: relative; aspect-ratio: 16 / 9; overflow: hidden;
        border-radius: 12px; box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
        border: 1px solid #1f2937; background: #020617;
        /* Sized so the whole video AND the chat fit on screen: the player
           never grows taller than the viewport leaves room for. */
        max-width: min(100%, calc((100vh - 280px) * 1.7778)); margin: 0 auto; width: 100%;
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
    /* The chat floats over the BOTTOM portion of the video, translucent —
       lifted 64px AND held clear of the right edge, so YouTube's own
       controls (play, volume, settings, the FULLSCREEN icon in the
       corner) are never covered from any angle. */
    #watchparty .video-wrapper .chat {
        position: absolute; left: 2%; right: max(15%, 180px); bottom: 64px; z-index: 7; gap: 8px;
        max-height: 50%; overflow-y: auto; padding: 10px;
        background: rgba(10, 8, 16, .62); backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
        border: 1px solid rgba(255, 156, 192, .28);
    }
    #watchparty .video-wrapper .chat .messages { max-height: 130px; margin-top: 0; }
    /* Quiet mode: 5 seconds of keyboard idle fades the overlay chat to
       95% transparent — the interface disappears, only the chat text
       stays ghosted over the film. Any key or a click revives it. */
    #watchparty .video-wrapper .chat { transition: background .6s, border-color .6s; }
    #watchparty .video-wrapper .chat.chat-quiet { background: rgba(10, 8, 16, .05); border-color: transparent;
        backdrop-filter: none; -webkit-backdrop-filter: none; }
    #watchparty .video-wrapper .chat.chat-quiet .chat-header,
    #watchparty .video-wrapper .chat.chat-quiet .input-area {
        opacity: 0; height: 0; min-height: 0; margin: 0; padding: 0; border: 0; overflow: hidden; pointer-events: none; }
    #watchparty .video-wrapper .chat.chat-quiet .message { background: none; border-color: transparent;
        text-shadow: 0 1px 3px rgba(0, 0, 0, .95), 0 0 8px rgba(0, 0, 0, .7); }
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
        <p>Every day SlowMoDating schedules one film from its romance playlist of 1,000 movies. Open the Watch
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

<!-- Slim: everything that sat above the player lives in one pop-down. -->
<section style="padding:10px 14px">
    <details class="chmenu"><summary>☰ Watch Party menu ▾</summary>
    <p class="links chmenu-list" style="margin:0;min-width:min(460px,92vw);padding:12px">
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
    </details>
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
        /* The on-video control bar, revealed on hover/focus. It rides the
           TOP of the video so it never sits over YouTube's own bottom
           controls (fullscreen included). */
        .wbar { position: absolute; left: 0; right: 0; top: 0; z-index: 6; display: flex; gap: 6px;
            align-items: center; flex-wrap: wrap; padding: 8px 10px 26px;
            background: linear-gradient(rgba(10,8,16,.88), transparent);
            opacity: 0; pointer-events: none; transition: opacity .18s; }
        .video-wrapper:hover .wbar, .wbar:focus-within, .wbar:has(details[open]) { opacity: 1; pointer-events: auto; }
        .wbar .chmenu-list { max-height: min(52vh, 300px); overflow: auto; }
        /* Fullscreen fullscreens the WRAPPER, not the bare iframe — the
           video fills the screen and the chat rides along on top. */
        #watchparty .video-wrapper:fullscreen { max-width: none; aspect-ratio: auto; width: 100%; height: 100%; border-radius: 0; border: 0; }
        #watchparty .video-wrapper::backdrop { background: #000; }
        .wbar button.quiet { margin: 0; padding: 5px 9px; font-size: 13px; background: rgba(255,255,255,.14);
            color: #fff; border: 0; border-radius: 8px; cursor: pointer; }
        .wbar a.wbar-link { color: #ffb8d2; font-size: 12.5px; text-decoration: none; }
    </style>
    <!-- The channel menus ride the same line as the ☰ menu and the
         Premium link — always visible, pop-down lists. -->
    <?php foreach (SlowDatingEngine::WATCH_CHANNEL_GROUPS as $groupLabel => $groupChannels): ?>
        <details class="chmenu">
            <summary><?= sd_e($groupLabel) ?> ▾</summary>
            <div class="chmenu-list">
                <?php foreach ($groupChannels as $slug): ?>
                    <a href="?chat=<?= sd_e($chatId) ?>&amp;ch=<?= sd_e($slug) ?>#w-showcase"<?= $ch === $slug ? ' class="on"' : '' ?>><?= sd_e((string) $channels[$slug]['label']) ?></a>
                <?php endforeach; ?>
            </div>
        </details>
    <?php endforeach; ?>
    <a href="?chat=<?= sd_e($chatId) ?>&amp;mode=premium" class="links" style="color:#ffb8d2;font-size:13px;<?= $mode === 'premium' ? 'font-weight:800;text-decoration:underline' : '' ?>">Premium together</a>
    <a href="advanced-watch-party.php" style="color:#ffd97a;font-size:13px">Advanced · BETA</a>
    <button type="button" id="wpg-open" style="margin:0;padding:6px 14px;font-size:12.5px;background:#3a2a3e;color:#ffc4da;vertical-align:middle">🎲 Games</button>
</section>

<div id="watchparty">
    <!-- The Watch Room module IS the player now: synced playback for the
         couple plus video chat overlaid on the picture (idle-hide, full
         screen with the chat, its own failure handling and engines), all
         in one frame. The showcase below still drives it — every pick
         lands in the room's shared playlist. -->
    <?php
    $override = $engine->watchPartyEmbed();
    $myDisplayName = (string) ($engine->profile($userId)['display_name'] ?: 'Member');
    $wpRoom = wp_watch_room($engine, $chatId, $userId, $myDisplayName, $film, $override);
    ?>
    <?php if ($wpRoom !== null): ?>
        <iframe id="wp-room" class="wp-room"
                src="video-chat-player/embed.php?room=<?= sd_e(rawurlencode((string) $wpRoom['id'])) ?>&amp;name=<?= sd_e(rawurlencode($myDisplayName)) ?>"
                title="Watch Room — synced player and video chat"
                allow="autoplay; fullscreen; clipboard-write" allowfullscreen></iframe>
        <p style="margin:0;font-size:12.5px;color:#9ca3af">Watch Room: the player and the video chat share one frame —
            the chat floats over the picture, tucks itself away when idle, and rides into full screen.
            <?= sd_e($filmLabel) ?> is queued for both of you; picks from the showcase below play for you both.</p>
    <?php else: ?>
        <div class="video-fallback" style="position:relative;padding:40px 20px;display:flex;flex-direction:column;gap:6px;align-items:center">
            <strong style="color:#fff;font-size:18px"><?= sd_e($filmLabel) ?></strong>
            <span style="color:#9ca3af;font-size:13px;max-width:48ch">The Watch Room could not start — refresh in a moment.</span>
        </div>
    <?php endif; ?>

    <?php if ($mode === 'premium'): ?>
    <?php $sync = $engine->watchSync($chatId, $userId); ?>
    <section style="margin-top:0">
        <h2>Premium together — Bring-Your-Own-YouTube-Account Sync</h2>
        <p style="margin:0 0 10px">The same model Teleparty uses: <strong style="color:#f3eef6">1.</strong> You and
            <?= sd_e($otherName) ?> are in this watch-party room. <strong style="color:#f3eef6">2.</strong> Each of
            you is signed into your own YouTube account in the embedded player above — YouTube Premium plays
            ad-free on your own subscription. <strong style="color:#f3eef6">3.</strong> SlowMoDating keeps the two
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

    <!-- The video chat lives INSIDE the Watch Room frame above. The
         couple's persistent slow chat (pacing, contact filtering, image
         sharing) continues in the Member app as always. -->
    <p class="links" style="margin:0;font-size:13px">Watching with <strong style="color:#f3eef6"><?= sd_e($otherName) ?></strong> ·
        chat over the movie in the player above ·
        <a href="index.php?tab=chats">your slow chat with <?= sd_e($otherName) ?> continues in the Member app</a>
        <?php if (!$status['unlocked']): ?>
            <span style="color:#9ca3af">(slow-chat rules apply there: <?= (int) $status['daily_message_limit'] ?> messages today, contact details filtered)</span>
        <?php endif; ?>
    </p>
</div>
<!-- The Advanced Watch Party user guide: comprehensive, one collapsed line
     until opened, so it never pushes the page apart. -->
<section style="padding:10px 14px">
    <details>
        <summary style="cursor:pointer;color:#ffd97a;font-weight:700;font-size:14px">📖 Advanced Watch Party · BETA — the complete user guide ▾</summary>
        <div style="margin-top:10px;font-size:13.5px;line-height:1.65;color:#c9bfd2">
            <h3 style="margin:10px 0 4px;color:#f3eef6">1. What it is</h3>
            <p style="margin:0 0 8px">The Advanced Watch Party is a separate product from this couple's Watch Party:
                standalone paid rooms for groups, in four modes — <strong style="color:#f3eef6">Couples, Friends,
                Family, and Creator</strong> — each with its own themes and room accent. Rooms hold 2 to 12 people.
                It is in <strong style="color:#ffd97a">BETA</strong>: everything below works today, and details may
                still change. Open it any time from <a href="advanced-watch-party.php" style="color:#ffd97a">Advanced
                Watch Party</a> (also under the Watch Party ▾ menu at the top of every page).</p>
            <h3 style="margin:10px 0 4px;color:#f3eef6">2. Bring your own YouTube (BYOYA)</h3>
            <p style="margin:0 0 8px">Everyone in the room watches signed into <em>their own</em> YouTube account, so
                YouTube Premium members get ad-free playback on their own subscription. The room fee pays for the
                sync service, chat, games, and recap — <strong style="color:#f3eef6">never for the movie</strong>.</p>
            <h3 style="margin:10px 0 4px;color:#f3eef6">3. Creating a room</h3>
            <p style="margin:0 0 8px">On the Advanced Watch Party page pick a mode and theme, set the price per
                person ($0 makes a free room) and how many participants are required, then choose the video:
                paste any YouTube video, playlist, or embed link — or click any thumbnail in the
                <strong style="color:#f3eef6">library at the bottom of the page</strong> (every Watch Party channel
                and every video is there) and it fills the form for you.</p>
            <h3 style="margin:10px 0 4px;color:#f3eef6">4. Invites and split payment</h3>
            <p style="margin:0 0 8px">Every room gets a six-character <strong style="color:#f3eef6">invite
                code</strong>. Share it; friends enter it under "Join with an invite code". In a priced room the
                session fee <strong style="color:#f3eef6">splits evenly</strong> and the room — player, shared
                controls, reactions, games — stays locked until every required share is paid. Each person pays
                their own share from the room page.</p>
            <h3 style="margin:10px 0 4px;color:#f3eef6">5. The player and shared controls</h3>
            <p style="margin:0 0 8px">Once unlocked, the room runs a <strong style="color:#f3eef6">server-authoritative
                shared timeline</strong>: ▶ Play together, ⏸ Pause both, and ⟲ Re-sync everyone keep every player
                locked to the same timecode. One person holds <strong style="color:#f3eef6">the remote</strong>
                (the host at first) and can pass it to anyone in the room.</p>
            <h3 style="margin:10px 0 4px;color:#f3eef6">6. Changing the video</h3>
            <p style="margin:0 0 8px">The full Watch Party library is on the room page — all channels
                (Movies, Live Nature cams, the twelve Relaxation channels, Faith) with the YouTube thumbnails as
                buttons, plus search inside each channel. Clicking a thumbnail
                <strong style="color:#f3eef6">swaps the room's video for everyone</strong> and restarts the shared
                timeline.</p>
            <h3 style="margin:10px 0 4px;color:#f3eef6">7. Reactions, highlights, and the emotion timeline</h3>
            <p style="margin:0 0 8px">React with 😂 😱 😢 ❤️ 🤩 🥱 while the film plays — bursts float over the video
                and land on the room's emotion timeline. When two people react within a second of each other, that
                counts as an <strong style="color:#f3eef6">emotion sync moment</strong>. Press
                ⭐ <em>Mark this moment</em> to save a timestamped highlight.</p>
            <h3 style="margin:10px 0 4px;color:#f3eef6">8. Room chat and background games</h3>
            <p style="margin:0 0 8px">The room chat sits under the player and never pauses the movie. The
                🎲 <strong style="color:#f3eef6">Games</strong> button opens the same background games the couple's
                Watch Party carries — tic-tac-toe, Connect Four, memory match, Would You Rather, movie trivia, and
                watch-party bingo — in a floating panel over the film. The first two people in the room hold the
                pieces; everyone else watches the board.</p>
            <h3 style="margin:10px 0 4px;color:#f3eef6">9. The recap</h3>
            <p style="margin:0 0 8px">When the host ends the session, everyone gets the recap: total reactions by
                type, the most intense stretch of the film, every emotion sync moment, and all the marked
                highlights — the story of the night, in numbers.</p>
            <h3 style="margin:10px 0 4px;color:#f3eef6">10. Good to know</h3>
            <p style="margin:0">Rooms are free to create at $0. Only participants can see a room, change its video,
                or play its games. The couple's Watch Party (this page) stays unchanged — same chat rules, same
                pacing, same safety filters.</p>
        </div>
    </details>
</section>

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
        // The Watch Room module owns the player, the video chat overlay,
        // fullscreen, idle-hide, and failure recovery — the page-side
        // player/chat scripting that used to live here is retired.

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

        // The Watch Room module owns rotation, failure recovery, and slot
        // control now; the legacy player handle stays null-guarded for the
        // premium panel below.
        var player = document.getElementById('wp-player');

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

<!-- The channel showcase renders in EVERY mode (Premium included) so the
     nature cams, rooftop cams, and the rest are always one click away. -->
<section id="w-showcase">
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
            <div class="card" style="padding:12px">
                <?php if (!empty($entry['youtube_id'])): ?>
                    <!-- The YouTube thumbnail IS the button: the art sells the video. -->
                    <form method="post" style="background:none;border:0;padding:0;margin:0 0 8px">
                        <input type="hidden" name="action" value="pick">
                        <input type="hidden" name="chat_id" value="<?= sd_e($chatId) ?>">
                        <input type="hidden" name="film_id" value="<?= sd_e((string) $entry['id']) ?>">
                        <button type="submit" title="Watch <?= sd_e((string) $entry['title']) ?>"
                                style="display:block;width:100%;padding:0;margin:0;border:0;background:none;cursor:pointer;border-radius:10px;overflow:hidden">
                            <img src="https://i.ytimg.com/vi/<?= sd_e((string) $entry['youtube_id']) ?>/mqdefault.jpg" alt=""
                                 loading="lazy" style="display:block;width:100%;aspect-ratio:16/9;object-fit:cover"
                                 onerror="this.onerror=null;this.src='data:image/svg+xml;charset=utf8,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 160 90%27%3E%3Crect width=%27160%27 height=%2790%27 fill=%27%23262030%27/%3E%3Ctext x=%2780%27 y=%2754%27 font-size=%2728%27 text-anchor=%27middle%27 fill=%27%23ffb8d2%27%3E%E2%96%B6%3C/text%3E%3C/svg%3E'">
                        </button>
                    </form>
                <?php endif; ?>
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

<?php sd_page_close();
