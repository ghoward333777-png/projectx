<?php

declare(strict_types=1);

/**
 * SlowDating browse library seeder.
 *
 * ADDS a library of 50 demo members — 25 women and 25 men — with varied,
 * realistic profiles, procedurally generated avatar portraits (served by
 * avatar.php), layered popularity, and a profile-video link each (a
 * placeholder YouTube clip standing in for the member's own video; the
 * profile video policy is clips of at most 10 seconds).
 *
 * Unlike seed-demo.php this script does NOT wipe existing state: run it
 * on top of the demo world (or an empty install) to fill Browse, Search,
 * and Matches with a full community. Running it twice is safe — members
 * that already exist (by email) are skipped.
 *
 *     php dating/bin/seed-demo.php        # optional: the guided demo world
 *     php dating/bin/seed-browse-library.php
 *
 * Demo use only.
 */

require_once __DIR__ . '/../SlowDatingEngine.php';

$engine = new SlowDatingEngine(new SlowDatingStore(dirname(__DIR__) . '/state'));
$now = time();
$day = 86400;

$women = ['Ava', 'Mia', 'Zoe', 'Lily', 'Nora', 'Ruby', 'Isla', 'Cora', 'Jade', 'Elle',
          'Maya', 'Tess', 'Rosa', 'Iris', 'Faye', 'Nina', 'Skye', 'Vera', 'Luna', 'Dana',
          'Gwen', 'Hope', 'June', 'Kira', 'Wren'];
$men = ['Liam', 'Noah', 'Owen', 'Eli', 'Jack', 'Cole', 'Ryan', 'Seth', 'Adam', 'Joel',
        'Finn', 'Dean', 'Hugo', 'Marc', 'Theo', 'Reid', 'Kyle', 'Evan', 'Luke', 'Sam',
        'Nate', 'Paul', 'Ross', 'Todd', 'Wade'];

$interestPool = ['jazz', 'wine', 'travel', 'italian food', 'dancing', 'art', 'cruises',
                 'hiking', 'coffee', 'escape rooms', 'film', 'opera', 'cooking', 'sailing',
                 'photography', 'yoga', 'tennis', 'board games', 'live music', 'poetry'];
$hobbyPool = ['hiking', 'painting', 'salsa', 'chess', 'running', 'guitar', 'kayaking',
              'baking', 'climbing', 'gardening', 'cycling', 'pottery'];
$outdoorPool = ['hiking', 'sailing', 'beach volleyball', 'running', 'climbing',
                'kayaking', 'cycling', 'camping'];
$zips = ['90210', '90211', '90212', '90213', '90214', '90024', '90403', '90001', '90045', '91101'];
$occupations = ['tech', 'finance', 'medical', 'legal', 'arts', 'education', 'service',
                'government', 'entrepreneur', 'marketing'];
$faiths = ['none', 'christian', 'catholic', 'jewish', 'spiritual', 'none', 'christian'];
$politicsPool = ['liberal', 'conservative', 'moderate', 'apolitical', 'moderate'];
$types = SlowDatingEngine::DATING_TYPES;
$incomes = SlowDatingEngine::INCOME_RANGES;
$autos = SlowDatingEngine::AUTOMOBILES;

// Placeholder public clips standing in for members' own <=10s videos.
$videoIds = ['dQw4w9WgXcQ', 'jNQXAC9IVRw', '9bZkp7q19f0', 'aqz-KE-bpKQ',
             'ScMzIvxBSi4', 'kJQP7kiw5Fk', 'ZZ5LpwO-An4', 'hY7m5jjJ9mM'];

/**
 * A deterministic sample "profile photo": abstract head-and-shoulders
 * portrait art rendered with GD (PNG, 480x480). Clearly synthetic — no
 * real faces — but reads as a profile picture in every card. Returns
 * null when the GD extension is unavailable.
 */
function sample_portrait(int $i): ?string
{
    if (!extension_loaded('gd')) {
        return null;
    }
    $palettes = [
        [[59, 30, 63], [255, 156, 192]], [[30, 42, 74], [143, 184, 255]],
        [[23, 58, 46], [127, 227, 168]], [[74, 36, 16], [255, 176, 138]],
        [[58, 16, 58], [224, 138, 255]], [[16, 58, 58], [127, 222, 222]],
        [[64, 50, 15], [255, 217, 122]], [[43, 17, 64], [180, 156, 255]],
    ];
    [$deep, $soft] = $palettes[$i % 8];
    $img = imagecreatetruecolor(480, 480);
    for ($y = 0; $y < 480; $y++) {
        $t = $y / 480;
        $line = imagecolorallocate(
            $img,
            (int) ($deep[0] + ($soft[0] - $deep[0]) * $t),
            (int) ($deep[1] + ($soft[1] - $deep[1]) * $t),
            (int) ($deep[2] + ($soft[2] - $deep[2]) * $t),
        );
        imageline($img, 0, $y, 480, $y, $line);
    }
    $halo = imagecolorallocatealpha($img, 255, 255, 255, 96);
    imagefilledellipse($img, 240, 210, 300 + ($i * 13) % 60, 300 + ($i * 13) % 60, $halo);
    $tone = imagecolorallocate($img, (int) ($deep[0] * .55), (int) ($deep[1] * .55), (int) ($deep[2] * .55));
    if ($i % 2 === 0) { // longer hair silhouette on alternating portraits
        imagefilledellipse($img, 240, 220, 232, 264, $tone);
    }
    imagefilledellipse($img, 240, 205, 176, 190, $tone);            // head
    imagefilledellipse($img, 240, 470, 340, 230, $tone);            // shoulders
    ob_start();
    imagepng($img);
    imagedestroy($img);
    return (string) ob_get_clean();
}

$roster = [];
foreach ($women as $i => $name) {
    $roster[] = ['female', $name, $i];
}
foreach ($men as $i => $name) {
    $roster[] = ['male', $name, $i + 25];
}

$created = 0;
$skipped = 0;
foreach ($roster as [$gender, $name, $i]) {
    $email = strtolower($name) . sprintf('%02d', $i) . '@library.demo';
    if ($engine->store()->where('users', ['email' => $email]) !== []) {
        $skipped++;
        continue;
    }
    $joined = $now - (10 + ($i * 3) % 70) * $day;
    $member = $engine->signupMember($email, null, true, $joined);
    $id = $member['user_id'];

    // Deterministic, varied profile facts from the roster index.
    $interests = [
        $interestPool[$i % 20],
        $interestPool[($i * 3 + 4) % 20],
        $interestPool[($i * 7 + 11) % 20],
    ];
    $engine->updateProfile($id, [
        'display_name' => $name,
        'age' => 21 + (($i * 7) % 25),
        'gender' => $gender,
        'zip_code' => $zips[$i % 10],
        'interests' => array_values(array_unique($interests)),
        'hobbies' => [$hobbyPool[$i % 12], $hobbyPool[($i * 5 + 3) % 12]],
        'outdoor_activities' => [$outdoorPool[$i % 8]],
        'dating_type' => $types[$i % 5],
        'faith' => $faiths[$i % 7],
        'politics' => $politicsPool[$i % 5],
        'income_range' => $incomes[$i % 5],
        'automobile' => $autos[$i % 8],
        'occupation_category' => $occupations[$i % 10],
    ]);
    $engine->addProfileVideo($id, 'https://www.youtube.com/watch?v=' . $videoIds[$i % 8]);
    // Every profile carries its three pictures: generated artwork
    // (automatic), a real-picture stand-in, and a distinct private one.
    $portrait = sample_portrait($i);
    if ($portrait !== null) {
        $engine->setMemberPhoto($id, $portrait, 'image/png', 'public');
        $engine->setMemberPhoto($id, (string) sample_portrait($i + 61), 'image/png', 'private');
    }

    // Layered popularity so Browse ranks with texture.
    $views = 4 + ($i * 11) % 40;
    $likes = ($i * 5) % 14;
    $compliments = ($i * 3) % 6;
    for ($j = 0; $j < $views; $j++) {
        $engine->recordPopularityEvent($id, 'profile_view', $now - (($j * 5 + $i) % 13) * $day - 3600);
    }
    for ($j = 0; $j < $likes; $j++) {
        $engine->recordPopularityEvent($id, 'like', $now - (($j * 4 + $i) % 12) * $day - 5400);
    }
    for ($j = 0; $j < $compliments; $j++) {
        $engine->recordPopularityEvent($id, 'compliment', $now - (($j * 6 + $i) % 11) * $day - 7200);
    }

    // Everyone in the library has saved browse preferences.
    $age = 21 + (($i * 7) % 25);
    $engine->updatePreferences($id, [
        'seeking_gender' => $gender === 'female' ? 'male' : 'female',
        'age_min' => max(18, $age - 6),
        'age_max' => $age + 8,
        'max_distance_km' => [25, 50, 120][$i % 3],
    ]);
    $created++;
}

// Demo worlds show the sample portraits: switch the platform to uploaded
// images (admins can flip back to generated artwork in the console).
$engine->store()->put('settings', 'avatar_mode', ['value' => 'uploads']);

echo "Browse library: {$created} members created, {$skipped} already present.\n";
echo "Profile-image mode set to 'uploads' — sample portraits show on cards (admin can switch back).\n";
echo "Women: " . count($women) . " · Men: " . count($men) . " · each with profile, avatar, video link, popularity, and saved preferences.\n";
echo "Profile video policy: clips of 10 seconds or less.\n";
