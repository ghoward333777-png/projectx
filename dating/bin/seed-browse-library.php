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

echo "Browse library: {$created} members created, {$skipped} already present.\n";
echo "Women: " . count($women) . " · Men: " . count($men) . " · each with profile, avatar, video link, popularity, and saved preferences.\n";
echo "Profile video policy: clips of 10 seconds or less.\n";
