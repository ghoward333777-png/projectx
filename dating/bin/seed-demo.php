<?php

declare(strict_types=1);

/**
 * SlowDating demo seeder.
 *
 * Resets the app state and fills it with a realistic demo: six members, a
 * chat on day 12 of the slow phase (with a filtered contact-sharing
 * attempt), an unlocked 36-day chat, three partner venues with coupons,
 * a singles event, a contest, store products, and an admin who has run two
 * top-10 reward campaigns. Run from anywhere:
 *
 *     php dating/bin/seed-demo.php
 *
 * Demo logins (all pages under dating/):
 *     Member   index.php           alice@demo.example    Demo!Alice2026#
 *     Partner  partner-portal.php  owner@bluenote.example Demo!Partner2026#
 *     Admin    admin.php           admin@slowdating.example Demo!Admin2026#
 *
 * WARNING: this wipes dating/state. Demo use only.
 */

require_once __DIR__ . '/../SlowDatingEngine.php';

$stateDir = dirname(__DIR__) . '/state';
exec('rm -rf ' . escapeshellarg($stateDir));
$engine = new SlowDatingEngine(new SlowDatingStore($stateDir));
$now = time();
$day = 86400;

// ---- Members ---------------------------------------------------------------
$members = [
    'alice' => ['alice@demo.example', 'Demo!Alice2026#', [
        'display_name' => 'Alice', 'age' => 29, 'gender' => 'female', 'zip_code' => '90210',
        'interests' => 'jazz, italian food, travel', 'hobbies' => 'photography, hiking',
        'outdoor_activities' => 'hiking, kayaking', 'dating_type' => 'long_term', 'faith' => 'none',
        'politics' => 'moderate', 'income_range' => '60k_100k', 'automobile' => 'ev',
        'occupation_category' => 'tech',
    ]],
    'bob' => ['bob@demo.example', 'Demo!Bob2026#', [
        'display_name' => 'Bob', 'age' => 33, 'gender' => 'male', 'zip_code' => '90211',
        'interests' => 'jazz, wine, travel', 'hobbies' => 'hiking, cooking',
        'outdoor_activities' => 'hiking', 'dating_type' => 'long_term', 'faith' => 'none',
        'politics' => 'moderate', 'income_range' => '100k_150k', 'automobile' => 'sedan',
        'occupation_category' => 'finance',
    ]],
    'marcus' => ['marcus@demo.example', 'Demo!Marcus2026#', [
        'display_name' => 'Marcus', 'age' => 31, 'gender' => 'male', 'zip_code' => '90210',
        'interests' => 'italian food, escape rooms, film', 'hobbies' => 'chess, running',
        'outdoor_activities' => 'running', 'dating_type' => 'long_term', 'faith' => 'spiritual',
        'politics' => 'liberal', 'income_range' => '60k_100k', 'automobile' => 'suv',
        'occupation_category' => 'medical',
    ]],
    'emma' => ['emma@demo.example', 'Demo!Emma2026#', [
        'display_name' => 'Emma', 'age' => 26, 'gender' => 'female', 'zip_code' => '90212',
        'interests' => 'dancing, wine, art', 'hobbies' => 'salsa, painting',
        'outdoor_activities' => 'beach volleyball', 'dating_type' => 'slow_dating', 'faith' => 'christian',
        'politics' => 'apolitical', 'income_range' => '30k_60k', 'automobile' => 'economy',
        'occupation_category' => 'arts',
    ]],
    'sofia' => ['sofia@demo.example', 'Demo!Sofia2026#', [
        'display_name' => 'Sofia', 'age' => 34, 'gender' => 'female', 'zip_code' => '90214',
        'interests' => 'cruises, fine dining, opera', 'hobbies' => 'sailing',
        'outdoor_activities' => 'sailing', 'dating_type' => 'marriage', 'faith' => 'catholic',
        'politics' => 'conservative', 'income_range' => '150k_plus', 'automobile' => 'luxury',
        'occupation_category' => 'legal',
    ]],
    'james' => ['james@demo.example', 'Demo!James2026#', [
        'display_name' => 'James', 'age' => 28, 'gender' => 'male', 'zip_code' => '90213',
        'interests' => 'jazz, hiking, coffee', 'hobbies' => 'guitar',
        'outdoor_activities' => 'hiking, climbing', 'dating_type' => 'slow_dating', 'faith' => 'none',
        'politics' => 'liberal', 'income_range' => '30k_60k', 'automobile' => 'none',
        'occupation_category' => 'education',
    ]],
];
$ids = [];
foreach ($members as $key => [$email, $password, $profile]) {
    $result = $engine->signupMember($email, $password, false, $now - 40 * $day);
    $ids[$key] = $result['user_id'];
    $engine->updateProfile($result['user_id'], $profile);
}
$engine->addProfileVideo($ids['alice'], 'https://www.youtube.com/watch?v=dQw4w9WgXcQ');
$engine->updatePreferences($ids['alice'], ['seeking_gender' => 'male', 'age_min' => 27, 'age_max' => 38, 'max_distance_km' => 50]);
$engine->updatePreferences($ids['bob'], ['seeking_gender' => 'female', 'age_min' => 25, 'age_max' => 36, 'max_distance_km' => 50]);
$engine->updatePreferences($ids['emma'], ['seeking_gender' => 'male', 'age_min' => 25, 'age_max' => 35, 'dating_type' => 'slow_dating']);

// ---- Chat 1: Alice <-> Bob, day 12 of slow chat ------------------------------
$chat1 = $engine->startChat($ids['bob'], $ids['alice'], $now - 12 * $day);
$c1 = (string) $chat1['id'];
$script = [
    [12, 'bob', "Hi Alice — your photo from the Amalfi coast stopped my scroll. Where was that taken?"],
    [12, 'alice', "Positano! Shot it at sunrise before the crowds. You have a great smile in that vineyard photo, by the way."],
    [11, 'bob', "Ha, thank you — that was a wine tasting in Paso Robles. So: jazz AND italian food on your profile. Bold combination."],
    [11, 'alice', "The only combination. A quiet lounge with a live trio and a plate of handmade pasta is my perfect evening."],
    [10, 'bob', "Noted. What's playing in your headphones lately?"],
    [10, 'alice', "A lot of Bill Evans. And one guilty-pleasure playlist I will not be disclosing this early."],
    [9, 'bob', "This slow pace is killing me in the best way. What neighborhood are you in, roughly?"],
    [9, 'alice', "Roughly? The one with the good espresso. You'll get coordinates in 21 days."],
    [8, 'bob', "Fair. Consider me thoroughly paced. Tell me about the photography — film or digital?"],
    [8, 'alice', "Both. Film for people, digital for travel. There's a jazz brunch downtown I keep meaning to shoot."],
    [6, 'bob', "A jazz brunch sounds suspiciously like a first date waiting to happen."],
    [6, 'alice', "It does, doesn't it. 18 more days and 2 more real conversations and you can plan it properly."],
    [4, 'bob', "Counting down. Meanwhile: best pasta shape, and defend your answer."],
    [4, 'alice', "Orecchiette. It's a tiny bowl that carries the sauce. This is not a debate."],
    [1, 'bob', "I brought up orecchiette at dinner with friends and started an argument. Worth it."],
    [1, 'alice', "My work here is done. Same time tomorrow?"],
    [0.2, 'bob', "Screw the pace for one second — here's my number: 310-555-0142, and I'm @bobonwine on IG. For when you're ready."],
    [0.15, 'alice', "The app caught that before I even saw it. Earn the number, Bob — 18 more days."],
];
foreach ($script as [$daysAgo, $who, $text]) {
    $engine->sendMessage($c1, $ids[$who], $text, (int) round($now - $daysAgo * $day + ($who === 'bob' ? 3600 : 7200)));
}

// ---- Chat 2: Alice <-> Marcus, unlocked (36 days, 10 sessions) ----------------
$chat2 = $engine->startChat($ids['marcus'], $ids['alice'], $now - 36 * $day);
$c2 = (string) $chat2['id'];
for ($i = 0; $i < 10; $i++) {
    $ts = $now - (34 - $i * 3) * $day;
    $engine->sendMessage($c2, $ids['marcus'], ['So an escape room team of two — are we the puzzle people or the "read the room aloud" people?', 'I keep thinking about that detective game downtown. Saturday?', 'Third clue would have beaten us without you.', 'Coffee after the next one?', 'You pick the theme this time.', 'The Sherlock room has a 45-minute record. We can take it.', 'Rematch. I have a strategy now.', 'Strategy failed but dignity intact.', 'OK the noir room. Final answer.', 'This has been the best month on any app, for the record.'][$i], $ts);
    $engine->sendMessage($c2, $ids['alice'], ['Puzzle people. Obviously.', 'Saturday works — loser buys espresso.', 'We make a scary-good team.', 'Always coffee after.', 'Noir theme. Trench coats optional but encouraged.', '43 minutes or nothing.', 'Bring the strategy, I\'ll bring the win.', 'Dignity is negotiable, espresso is not.', 'Deal.', 'Agreed. And now the app finally trusts us…'][$i], $ts + 1800);
}
$engine->sendMessage($c2, $ids['marcus'], "Real-time at last. Here's my actual number: 424-555-0177 — call me about Saturday.", $now - 2 * $day);
$engine->sendMessage($c2, $ids['alice'], 'Saved! Mine is 310-555-0126. See you at the noir room, detective.', $now - 2 * $day + 600);
$engine->sendMessage($c2, $ids['marcus'], 'Dinner first? That little Italian place near the theater — are you free Saturday?', $now - $day);
$engine->sendMessage($c2, $ids['alice'], 'Perfect. Pasta, then a late movie. It\'s a date.', $now - $day + 300);

// ---- Extra popularity so the leaderboard has texture ---------------------------
$sprinkle = [
    'alice' => ['profile_view' => 34, 'like' => 12, 'photo_received' => 3, 'event_invite' => 2],
    'emma' => ['profile_view' => 28, 'like' => 15, 'chat_request' => 6, 'compliment' => 4],
    'sofia' => ['profile_view' => 19, 'like' => 7, 'chat_request' => 3],
    'bob' => ['profile_view' => 14, 'like' => 5, 'compliment' => 2],
    'marcus' => ['profile_view' => 11, 'like' => 4],
    'james' => ['profile_view' => 8, 'like' => 3, 'chat_request' => 2],
];
foreach ($sprinkle as $who => $events) {
    $i = 0;
    foreach ($events as $type => $count) {
        for ($j = 0; $j < $count; $j++) {
            $engine->recordPopularityEvent($ids[$who], $type, $now - (($i * 7 + $j * 3) % 13) * $day - 3600);
            $i++;
        }
    }
}

// Alice is having a good week: recent attention outweighs the prior week.
for ($j = 0; $j < 14; $j++) {
    $engine->recordPopularityEvent($ids['alice'], $j % 3 === 0 ? 'like' : 'profile_view', $now - ($j % 5) * $day - 7200);
}

// ---- Partners ------------------------------------------------------------------
$blueNote = $engine->signupPartner('Blue Note Lounge', 'owner@bluenote.example', 'Demo!Partner2026#', 'pro', $now - 30 * $day);
$bnVenue = $engine->createVenue($blueNote['partner_id'], [
    'name' => 'Blue Note Lounge', 'address' => '412 Canon Dr', 'zip_code' => '90210', 'category' => 'lounge',
    'atmosphere_tags' => ['jazz', 'quiet', 'romantic', 'no_kids'],
], $now - 30 * $day);
$bnEvent = $engine->createEvent($blueNote['partner_id'], (string) $bnVenue['id'], [
    'title' => 'Singles Jazz Night — Autumn Session', 'description' => 'Live trio, low lights, conversation-friendly volume. Members only.',
    'date_time' => $now + 9 * $day, 'capacity' => 60, 'tags' => ['singles', 'jazz', 'quiet'], 'ticket_price' => 25.0,
], $now - 10 * $day);
$engine->createContest($blueNote['partner_id'], (string) $bnVenue['id'], [
    'prize' => 'Dinner for two + reserved stage table', 'rules' => 'Every Jazz Night ticket is an entry. Winner drawn at the event.',
    'event_id' => (string) $bnEvent['id'], 'start_date' => $now - 10 * $day, 'end_date' => $now + 9 * $day, 'draw_date' => $now + 9 * $day,
], $now - 10 * $day);
$engine->createTargetedCoupon($blueNote['partner_id'], (string) $bnVenue['id'], [
    'discount_type' => 'percent', 'discount_amount' => 20, 'max_recipients' => 100,
    'valid_from' => $now - 5 * $day, 'valid_to' => $now + 25 * $day,
], ['gender' => 'female', 'age_min' => 21, 'age_max' => 35, 'zip_radius_km' => 30], $now - 5 * $day);
$engine->createProduct($blueNote['partner_id'], (string) $bnVenue['id'], [
    'name' => 'Vinyl & Wine Date Kit', 'description' => 'A pressed jazz LP, two glasses, and a tasting card for a night in.',
    'category' => 'date-night kit', 'price' => 59.0, 'inventory' => 18,
], $now - 5 * $day);

$cipher = $engine->signupPartner('Cipher Rooms', 'hello@cipherrooms.example', 'Demo!Partner2026#', 'elite', $now - 20 * $day);
$cipherVenue = $engine->createVenue($cipher['partner_id'], [
    'name' => 'Cipher Rooms', 'address' => '88 Mystery Ln', 'zip_code' => '90211', 'category' => 'experience',
    'atmosphere_tags' => ['game_night', 'no_kids'],
], $now - 20 * $day);
$engine->createEvent($cipher['partner_id'], (string) $cipherVenue['id'], [
    'title' => 'Detective Night for Two', 'description' => 'Solve a 1940s noir case together. Includes espresso debrief.',
    'date_time' => $now + 5 * $day, 'capacity' => 24, 'tags' => ['game_night', 'singles'], 'ticket_price' => 38.0,
], $now - 8 * $day);
$engine->createProduct($cipher['partner_id'], (string) $cipherVenue['id'], [
    'name' => 'At-Home Mystery Box', 'description' => 'A two-player detective case in a box — 90 minutes of clues.',
    'category' => 'experience', 'price' => 44.5, 'inventory' => 30,
], $now - 8 * $day);

// Meet-up advertisers: the second ad that flashes when a couple starts
// arranging a date whose plans match the purchased keys.
$ralphs = $engine->signupPartner("Ralph's Italian Spot", 'ralph@ralphsitalian.example', 'Demo!Partner2026#', 'pro', $now - 12 * $day);
$ralphsVenue = $engine->createVenue($ralphs['partner_id'], [
    'name' => "Ralph's Italian Spot", 'address' => '12 Vine St', 'zip_code' => '90210', 'category' => 'restaurant',
    'atmosphere_tags' => ['romantic', 'quiet', 'no_kids'],
], $now - 12 * $day);
$engine->createMeetupAd($ralphs['partner_id'], (string) $ralphsVenue['id'], [
    'headline' => "Make it Ralph's before the show",
    'message' => 'Handmade pasta, corner tables, and out in time for the trailers.',
    'offer' => 'Mention SlowDating for free tiramisu',
    'keys' => ['italian_restaurant', 'fine_dining'],
], $now - 12 * $day);
$theater = $engine->signupPartner('Double Feature Theater', 'box@doublefeature.example', 'Demo!Partner2026#', 'pro', $now - 12 * $day);
$theaterVenue = $engine->createVenue($theater['partner_id'], [
    'name' => 'Double Feature Theater', 'address' => '48 Marquee Ave', 'zip_code' => '90211', 'category' => 'experience',
    'atmosphere_tags' => ['no_kids', 'quiet'],
], $now - 12 * $day);
$engine->createMeetupAd($theater['partner_id'], (string) $theaterVenue['id'], [
    'headline' => 'Two seats at the Double Feature',
    'message' => 'Classic late showings, loveseat rows in the back.',
    'offer' => 'Couples get two-for-one Saturdays',
    'keys' => ['movies'],
], $now - 12 * $day);

$trattoria = $engine->signupPartner('Trattoria Luna', 'ciao@trattorialuna.example', 'Demo!Partner2026#', 'basic', $now - 15 * $day);
$tratVenue = $engine->createVenue($trattoria['partner_id'], [
    'name' => 'Trattoria Luna', 'address' => '7 Via Roma', 'zip_code' => '90210', 'category' => 'restaurant',
    'atmosphere_tags' => ['romantic', 'quiet', 'no_kids'],
], $now - 15 * $day);
$engine->createRandomCoupon($trattoria['partner_id'], (string) $tratVenue['id'], [
    'discount_type' => 'fixed', 'discount_amount' => 15, 'max_recipients' => 50,
    'valid_from' => $now - 3 * $day, 'valid_to' => $now + 27 * $day,
], $now - 3 * $day);

// Alice buys Jazz Night tickets (auto contest entry) and a mystery box order exists.
$engine->buyTicket((string) $bnEvent['id'], $ids['alice'], 2, $now - 4 * $day);
$engine->buyTicket((string) $bnEvent['id'], $ids['emma'], 1, $now - 3 * $day);
foreach ($engine->products() as $product) {
    if ($product['name'] === 'At-Home Mystery Box') {
        $engine->placeOrder($ids['sofia'], (string) $product['id'], 1, $now - 2 * $day);
    }
}

// ---- Admin + rewards ---------------------------------------------------------------
$admin = $engine->createAdmin('admin@slowdating.example', 'Demo!Admin2026#', null, $now - 30 * $day);
$engine->grantTopMemberRewards($admin['admin_id'], 10, ['type' => 'gift_certificate', 'amount' => 100.0], $now - 6 * $day);
$engine->grantTopMemberRewards($admin['admin_id'], 10, ['type' => 'promo_trip', 'description' => 'All-expense weekend at the SlowDating Spring Launch Gala in Napa'], $now - 1 * $day);

// ---- Photo reveal timeframe ----------------------------------------------------
// Pictures come second: real photos reveal on day 2 of a chat. Premium
// members (Alice, Emma below) hold the "Peek early" perk and skip the wait.
$engine->setPhotoRevealDays($admin['admin_id'], 2);

// ---- Perks & income: Alice is popular, enrolled, and already earning -------------
$engine->subscribeMembership($ids['alice'], 'vip', $now - 20 * $day);
$engine->subscribeMembership($ids['emma'], 'member', $now - 15 * $day);
foreach (['profile_ads', 'premium_gallery', 'chat_responder', 'chat_initiator', 'date_scheduler', 'testimonials'] as $program) {
    $engine->enrollEarnProgram($ids['alice'], $program, $now - 7 * $day);
}

// Profile-ad revenue: enrolled, so every profile view pays a share.
for ($j = 0; $j < 6; $j++) {
    $engine->recordPopularityEvent($ids['alice'], 'profile_view', $now - $j * 3600 - 1800);
}

// Premium Members Only gallery: two photos, and Emma (premium) visits.
if (extension_loaded('gd')) {
    $galleryShot = static function (int $seed): string {
        $img = imagecreatetruecolor(240, 240);
        for ($y = 0; $y < 240; $y++) {
            $shade = imagecolorallocate($img, (40 + $seed * 37 + $y) % 200 + 30, (90 + $seed * 53) % 180 + 40, (140 + $y + $seed * 71) % 190 + 40);
            imageline($img, 0, $y, 239, $y, $shade);
        }
        ob_start();
        imagepng($img);
        imagedestroy($img);
        return (string) ob_get_clean();
    };
    $engine->addGalleryPhoto($ids['alice'], $galleryShot(1), 'image/png', 'Golden hour on the pier', $now - 5 * $day);
    $engine->addGalleryPhoto($ids['alice'], $galleryShot(2), 'image/png', 'Backstage at the jazz brunch', $now - 4 * $day);
    $engine->viewGallery($ids['emma'], $ids['alice'], $now - 2 * $day);
}

// Paid chat hours: five active hours today responding to Marcus, then claimed.
for ($h = 5; $h >= 1; $h--) {
    $ts = $now - $h * 3600;
    if ($ts > $now - ($now % 86400)) {   // keep every message inside today (UTC)
        $engine->sendMessage($c2, $ids['alice'], 'Still here, detective — hour ' . (6 - $h) . ' of our marathon.', $ts);
    }
}
$engine->claimActivityEarnings($ids['alice'], $now);

// Scheduled date at a partner event: 10% of the ticket back.
$engine->buyTicket((string) $bnEvent['id'], $ids['alice'], 1, $now - 6 * 3600);

// Partner-scripted testimonials: one accepted (and paid), one open offer.
$bnScript = $engine->createTestimonialScript($blueNote['partner_id'], (string) $bnVenue['id'], [
    'title' => '30-second Jazz Night testimonial',
    'script' => 'I met someone real at Blue Note\'s Singles Jazz Night. Low lights, live trio, actual conversation — this is how dates should start.',
    'payout' => 40.0,
], $now - 6 * $day);
$aliceTestimonial = $engine->submitTestimonial($ids['alice'], (string) $bnScript['id'], 'https://youtu.be/dQw4w9WgXcQ', 'Recorded after the autumn session.', $now - 5 * $day);
$engine->reviewTestimonial($blueNote['partner_id'], (string) $aliceTestimonial['id'], 'accept', ['note' => 'Perfect read — running it on our page.'], $now - 4 * $day);
$engine->createTestimonialScript($ralphs['partner_id'], (string) $ralphsVenue['id'], [
    'title' => 'Date night at Ralph\'s',
    'script' => 'Our first real dinner was at Ralph\'s Italian Spot — handmade pasta, a corner table, and we still made the movie.',
    'payout' => 55.0,
], $now - 2 * $day);

echo "Demo data seeded into {$stateDir}\n";
echo "Member login:  alice@demo.example / Demo!Alice2026# (dating/index.php)\n";
echo "Partner login: owner@bluenote.example / Demo!Partner2026# (dating/partner-portal.php)\n";
echo "Admin login:   admin@slowdating.example / Demo!Admin2026# (dating/admin.php)\n";
