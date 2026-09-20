<?php

declare(strict_types=1);

require_once __DIR__ . '/SlowDatingEngine.php';
require_once __DIR__ . '/ui.php';

session_start();

/**
 * Perks & Income — the portal where popular members turn their standing
 * into income: profile ad revenue, the Premium Members Only gallery,
 * paid chat hours, date scheduling at partner events, partner-scripted
 * testimonials, and the opt-ins for the programs coming after launch.
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
            case 'enroll':
                $engine->enrollEarnProgram($userId, (string) ($_POST['program'] ?? ''));
                $notice = 'Enrolled — this program now pays into your earnings ledger.';
                break;
            case 'withdraw':
                $engine->withdrawEarnProgram($userId, (string) ($_POST['program'] ?? ''));
                $notice = 'Withdrawn from the program.';
                break;
            case 'claim_activity':
                $claim = $engine->claimActivityEarnings($userId);
                $paid = 0.0;
                foreach ($claim['programs'] as $line) {
                    $paid += (float) $line['amount'];
                }
                $notice = $paid > 0
                    ? sprintf('Claimed $%s for today\'s chat hours.', number_format($paid, 2))
                    : 'Nothing to claim yet today — four active chat hours unlock the payout (or today was already claimed).';
                break;
            case 'gallery_upload':
                $upload = $_FILES['photo'] ?? null;
                if ($upload === null || (int) $upload['error'] !== UPLOAD_ERR_OK) {
                    throw new InvalidArgumentException('Choose a JPEG, PNG, or WebP up to 2 MB.');
                }
                $engine->addGalleryPhoto(
                    $userId,
                    (string) file_get_contents((string) $upload['tmp_name']),
                    (string) $upload['type'],
                    (string) ($_POST['caption'] ?? ''),
                );
                $notice = 'Added to your Premium Members Only gallery.';
                break;
            case 'gallery_remove':
                $engine->removeGalleryPhoto($userId, (string) ($_POST['photo_id'] ?? ''));
                $notice = 'Gallery photo removed.';
                break;
            case 'submit_testimonial':
                $engine->submitTestimonial(
                    $userId,
                    (string) ($_POST['script_id'] ?? ''),
                    (string) ($_POST['video_url'] ?? ''),
                    (string) ($_POST['notes'] ?? ''),
                );
                $notice = 'Testimonial submitted — the partner will accept, reject, edit, or extend it.';
                break;
        }
    } catch (Throwable $exception) {
        $error = $exception->getMessage();
    }
}

sd_page_open('Perks & Income', 'SlowDating · income programs for popular members');
sd_flash($error, $notice);

if ($userId === null) {
    ?>
    <section>
        <h2>Popularity pays here</h2>
        <p>Popular members earn real income on SlowDating: a share of the ads shown on their profile,
            a Premium Members Only photo gallery that pays per visit, paid hours responding to and
            initiating chats, cash back on dates scheduled at partner events, and partner-scripted
            testimonial videos with a payout on every accepted recording.
            <a href="index.php">Sign in or create a free account</a> to see where you stand.</p>
    </section>
    <?php
    sd_page_close();
    exit;
}

$portal = $engine->earnPortal($userId);
$eligibility = $portal['eligibility'];
$earnings = $engine->earningsFor($userId);
$gallery = $engine->viewGallery($userId, $userId);
$scripts = $engine->testimonialScripts();
$myTestimonials = $engine->testimonialsForMember($userId);
$statusLabels = ['submitted' => 'awaiting review', 'accepted' => 'accepted — paid', 'rejected' => 'rejected', 'revise' => 'script edited — re-record', 'extended' => 'script extended — record the addition'];
?>

<section>
    <h2>Your standing</h2>
    <div class="grid">
        <div class="metric card"><strong><?= (int) $eligibility['popularity_score'] ?></strong><span>popularity score</span></div>
        <div class="metric card"><strong>top <?= (int) $eligibility['percentile'] ?>%</strong><span>of your cohort</span></div>
        <div class="metric card"><strong>$<?= number_format((float) $earnings['total'], 2) ?></strong><span>earned to date</span></div>
    </div>
    <?php if ($eligibility['eligible']): ?>
        <p class="notice" style="margin-top:12px">You qualify for the income programs. Enroll below — every payout lands in your ledger.</p>
    <?php else: ?>
        <p>Income programs open up once you are popular: <?= sd_e((string) $eligibility['requirement']) ?>
            Complete your three pictures, answer prompts, and keep conversations warm — the score follows.</p>
    <?php endif; ?>
</section>

<section>
    <h2>Income programs</h2>
    <div class="grid">
        <?php foreach ($portal['programs'] as $program): ?>
            <div class="card">
                <strong><?= sd_e((string) $program['label']) ?></strong>
                <span class="pill"><?= $program['status'] === 'live' ? 'live' : 'after launch' ?></span>
                <?php if ($program['enrolled']): ?><span class="pill">enrolled</span><?php endif; ?>
                <p style="margin:8px 0"><?= sd_e((string) $program['blurb']) ?></p>
                <p style="margin:8px 0"><em>Pays:</em> <?= sd_e((string) $program['pays']) ?></p>
                <form method="post" style="background:none;border:0;padding:0;margin:0">
                    <input type="hidden" name="action" value="<?= $program['enrolled'] ? 'withdraw' : 'enroll' ?>">
                    <input type="hidden" name="program" value="<?= sd_e((string) $program['program']) ?>">
                    <button type="submit"><?= $program['enrolled'] ? 'Withdraw' : ($program['status'] === 'live' ? 'Enroll' : 'Opt in') ?></button>
                </form>
            </div>
        <?php endforeach; ?>
    </div>
</section>

<section>
    <h2>Paid chat hours</h2>
    <p>Stay logged in for 4 to 8 hours a day keeping chats alive. An active hour is any hour you send at
        least one message — counted separately for chats you started and chats you are responding in.
        Four active hours unlock $<?= number_format(SlowDatingEngine::EARN_RATES['active_hour'], 2) ?> per hour; eight hours is the daily cap.</p>
    <form method="post" style="background:none;border:0;padding:0;margin:0">
        <input type="hidden" name="action" value="claim_activity">
        <button type="submit">Claim today's chat hours</button>
    </form>
</section>

<section>
    <h2>Premium Members Only gallery</h2>
    <p>A private body of work, separate from your three profile pictures. Only premium (paid) members can
        open it — and every visit pays you $<?= number_format(SlowDatingEngine::EARN_RATES['gallery_premium_view'], 2) ?> per viewer per day while you are enrolled.
        <?= count($gallery['photos']) ?>/<?= (int) $portal['gallery_limit'] ?> photos.</p>
    <?php if ($gallery['photos'] !== []): ?>
        <div class="grid">
            <?php foreach ($gallery['photos'] as $photo): ?>
                <div class="card">
                    <img src="photo.php?gallery=<?= sd_e((string) $photo['photo_id']) ?>" alt="Gallery photo" style="width:100%;border-radius:10px">
                    <?php if ($photo['caption'] !== ''): ?><p style="margin:6px 0 0"><?= sd_e((string) $photo['caption']) ?></p><?php endif; ?>
                    <form method="post" style="background:none;border:0;padding:0;margin:0">
                        <input type="hidden" name="action" value="gallery_remove">
                        <input type="hidden" name="photo_id" value="<?= sd_e((string) $photo['photo_id']) ?>">
                        <button type="submit">Remove</button>
                    </form>
                </div>
            <?php endforeach; ?>
        </div>
    <?php endif; ?>
    <form method="post" enctype="multipart/form-data">
        <h2>Add a gallery photo</h2>
        <input type="hidden" name="action" value="gallery_upload">
        <label>Photo (JPEG, PNG, or WebP — max 2 MB)</label>
        <input type="file" name="photo" accept="image/jpeg,image/png,image/webp" required>
        <label>Caption (optional)</label>
        <input name="caption" maxlength="120" placeholder="Golden hour on the pier">
        <button type="submit">Upload to gallery</button>
    </form>
</section>

<section>
    <h2>Partner testimonial offers</h2>
    <p>Advertising partners script these testimonials and set the payout. Record the script, submit the
        video, and the partner accepts (you are paid), rejects, edits the script for a re-record, or
        extends it with an addition.</p>
    <?php if ($scripts === []): ?>
        <p>No open offers right now — check back after the next partner campaign.</p>
    <?php endif; ?>
    <div class="grid">
        <?php foreach ($scripts as $script): ?>
            <div class="card">
                <strong><?= sd_e((string) $script['title']) ?></strong>
                <span class="pill"><?= sd_e((string) $script['venue_name']) ?></span>
                <span class="pill">$<?= number_format((float) $script['payout'], 2) ?> on acceptance</span>
                <p style="margin:8px 0;white-space:pre-line"><?= sd_e((string) $script['script']) ?></p>
                <form method="post" style="background:none;border:0;padding:0;margin:0">
                    <input type="hidden" name="action" value="submit_testimonial">
                    <input type="hidden" name="script_id" value="<?= sd_e((string) $script['id']) ?>">
                    <label>Your recorded video URL</label>
                    <input name="video_url" placeholder="https://youtu.be/..." required>
                    <label>Notes for the partner (optional)</label>
                    <input name="notes" maxlength="200">
                    <button type="submit">Submit testimonial</button>
                </form>
            </div>
        <?php endforeach; ?>
    </div>
    <?php if ($myTestimonials !== []): ?>
        <h2 style="margin-top:18px">Your submissions</h2>
        <table>
            <tr><th>Venue</th><th>Status</th><th>Payout</th><th>Current script</th></tr>
            <?php foreach ($myTestimonials as $testimonial): ?>
                <tr>
                    <td><?= sd_e((string) $testimonial['venue_name']) ?></td>
                    <td><?= sd_e($statusLabels[(string) $testimonial['status']] ?? (string) $testimonial['status']) ?></td>
                    <td>$<?= number_format((float) $testimonial['payout'], 2) ?></td>
                    <td style="white-space:pre-line"><?= sd_e((string) $testimonial['script_text']) ?></td>
                </tr>
            <?php endforeach; ?>
        </table>
    <?php endif; ?>
</section>

<section>
    <h2>Earnings ledger</h2>
    <?php if ($earnings['entries'] === []): ?>
        <p>No earnings yet. Enroll in a live program above and the first payout starts the ledger.</p>
    <?php else: ?>
        <table>
            <tr><th>When</th><th>Program</th><th>Amount</th><th>Detail</th></tr>
            <?php foreach (array_slice($earnings['entries'], 0, 25) as $entry): ?>
                <tr>
                    <td><?= sd_e(gmdate('M j, Y', (int) $entry['earned_at'])) ?></td>
                    <td><?= sd_e((string) (SlowDatingEngine::EARN_PROGRAMS[(string) $entry['program']]['label'] ?? $entry['program'])) ?></td>
                    <td>$<?= number_format((float) $entry['amount'], 2) ?></td>
                    <td><?= sd_e((string) $entry['note']) ?></td>
                </tr>
            <?php endforeach; ?>
        </table>
    <?php endif; ?>
</section>

<?php sd_page_close();
