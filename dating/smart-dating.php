<?php

declare(strict_types=1);

require_once __DIR__ . '/ui.php';

/**
 * Smart Dating — the education library behind the slow-dating philosophy.
 * One article per factoid: why intense attraction misleads, the neuroscience
 * underneath it, and how slow-built relationships win. Public page; the
 * article catalog is also served as JSON at ?format=json.
 */

function smart_dating_articles(): array
{
    return [
        [
            'slug' => 'why-strong-attraction-fails',
            'title' => 'Why the Strongest Initial Attractions Often Destroy Long-Term Relationships',
            'takeaway' => 'Slow-growing relationships last longer because they build attachment, trust, and shared identity — while the very forces that spark intense attraction (beauty, novelty, sexual chemistry, fantasy projection) can sabotage long-term stability.',
            'sections' => [
                ['h' => '1. Physical attraction — the shallow foundation problem',
                 'p' => ['Physical attraction is powerful, but it is non-specific. It tells you nothing about values, emotional maturity, compatibility, communication style, trauma history, or long-term goals. It creates a false sense of connection because the brain releases dopamine and oxytocin from visual stimulation alone, tricking people into believing "we have chemistry, therefore we have compatibility."'],
                 'ul' => ['Chemistry is a biological reaction, not a relationship skill.', 'Attraction fires in milliseconds; compatibility reveals itself over months.']],
                ['h' => '2. Instant gratification — the bond without the foundation',
                 'p' => ['Physical intimacy accelerates emotional bonding through oxytocin, dopamine, and vasopressin. These chemicals create a shortcut to closeness, making people feel bonded before they actually know each other.'],
                 'ul' => ['Attachment without knowledge.', 'Commitment without compatibility.', 'Emotional dependency without trust.', 'Fantasy bonding instead of real bonding — the illusion of a relationship where none exists.']],
                ['h' => '3. Psychologically unbalanced pairings',
                 'p' => ['Two people can be intensely drawn to each other because their wounds "fit": anxious + avoidant, narcissist + empath, caretaker + chaotic partner, trauma survivor + emotionally unavailable partner. These pairs feel magnetic because they activate childhood patterns — but what feels familiar is not always healthy. That is trauma chemistry, not love.']],
                ['h' => '4. Physically attracted but completely mismatched',
                 'p' => ['The classic "we look great together but can\'t function together." Different conflict styles, incompatible attachment styles, mismatched emotional needs, opposite life goals, and different communication patterns stay hidden while attraction is loud — until the relationship collapses under real-life pressure.']],
                ['h' => '5. Economic incompatibility — different worlds, different stress',
                 'p' => ['Money is never just money. It is security, lifestyle, expectations, social environment, future planning, and stress tolerance. Different economic worlds often mean different values, priorities, definitions of success, and conflict triggers. Attraction cannot overcome structural incompatibility.']],
                ['h' => '6. Educational mismatch — the communication breakdown',
                 'p' => ['Education shapes worldview, problem-solving, communication style, ambition, and intellectual curiosity. Two people can be wildly attracted yet unable to connect intellectually — leading to resentment, boredom, misunderstanding, separate social circles, and diverging long-term goals.']],
            ],
        ],
        [
            'slug' => 'why-we-ignore-red-flags',
            'title' => 'Why Humans Ignore Red Flags and Pursue Bad Relationships Anyway',
            'takeaway' => 'Humans pursue bad matches because our brains are wired for dopamine, validation, and emotional shortcuts — even when logic screams "danger." We are biological, emotional, and pattern-driven, not rational, in love.',
            'sections' => [
                ['h' => '1. Dopamine addiction',
                 'p' => ['Attraction and early romance create dopamine spikes comparable to gambling, drugs, alcohol, and adrenaline sports. People end up chasing the high, not the person.']],
                ['h' => '2. Loneliness',
                 'p' => ['Loneliness lowers standards, hides incompatibility, makes people cling to attention, and blurs the line between validation and love. It is one of the strongest drivers of bad relationship decisions.']],
                ['h' => '3. Fantasy projection',
                 'p' => ['Humans fall in love with potential, fantasy, an imagined future, and an idealized version of the partner — not the real person in front of them.']],
                ['h' => '4. Attachment wounds',
                 'p' => ['People repeat childhood patterns: chasing unavailable partners, trying to "fix" someone, seeking validation from harmful people, confusing chaos with passion. We are drawn to what feels familiar — even when it is destructive.']],
                ['h' => '5. Sexual chemistry overriding logic',
                 'p' => ['Physical chemistry creates a false sense of closeness that makes people overlook disrespect, incompatibility, emotional immaturity, and outright dealbreakers. The body says "yes" even when the mind says "run."']],
                ['h' => '6. Hope and optimism bias',
                 'p' => ['"This time will be different" — believed even when every piece of evidence says otherwise.']],
                ['h' => '7. Fear of starting over',
                 'p' => ['Starting over feels exhausting; people fear being alone, failing, being judged, or losing what little they have. Fear keeps people stuck in relationships that logic already rejected.']],
                ['h' => 'The core truth',
                 'p' => ['Slow-growing relationships work because they build trust, shared identity, emotional safety, communication, compatibility, and real intimacy. They grow from knowing, not fantasy.']],
            ],
        ],
        [
            'slug' => 'neuroscience-of-attraction',
            'title' => 'The Neuroscience of Attraction',
            'takeaway' => 'Attraction is not magic — it is neurobiology. The brain uses chemicals, circuits, and ancient survival systems to decide who feels irresistible, who feels "safe," and who feels like a bad idea we pursue anyway.',
            'sections' => [
                ['h' => '1. The dopamine reward system — the "I want more" circuit',
                 'p' => ['Dopamine spikes on novelty, beauty, mystery, and unpredictability. It evolved to push humans toward exploration and mating — it creates anticipation, obsession, motivation, and risk-taking. Dopamine never says "this person is good for you." It says "this feels exciting — go." The brain confuses intensity with value, which is why people chase bad matches, unavailable people, and chaotic relationships.']],
                ['h' => '2. Oxytocin and vasopressin — the bonding chemicals',
                 'p' => ['Released through touch, eye contact, intimacy, and emotional vulnerability, these chemicals create trust, loyalty, a sense of safety, and emotional merging. The trap: the brain bonds even when the partner is a terrible match. That is why people stay in relationships logic says should end.']],
                ['h' => '3. The limbic system — emotional memory and pattern recognition',
                 'p' => ['The limbic system decides who feels "right" based on childhood experience, attachment style, trauma history, and early emotional conditioning. It produces pattern attraction: anxious people chase avoidant partners, empaths chase narcissists, caretakers chase chaos. The brain is drawn to what feels familiar — even when it is harmful.']],
                ['h' => '4. The visual cortex — why looks hit harder than logic',
                 'p' => ['Attractiveness is processed in milliseconds — fertility signals, health indicators, symmetry — creating instant attraction before the prefrontal cortex (logic) even wakes up. This is why beautiful people override red flags and why the brain prioritizes reproduction over rationality.']],
                ['h' => '5. The amygdala — fear, excitement, and danger attraction',
                 'p' => ['The amygdala responds to intensity, unpredictability, emotional highs and lows, and mystery — the "rollercoaster relationship" effect. Unstable partners trigger adrenaline, cortisol, and dopamine at once. That cocktail feels like passion; it is actually stress bonding.']],
                ['h' => '6. The prefrontal cortex — the judgment that arrives late',
                 'p' => ['This is the part that should say "this is a red flag; this will end badly." During early attraction it is suppressed by dopamine, oxytocin, arousal, and fantasy projection — which is why smart, successful people make terrible relationship choices.']],
                ['h' => 'Why attraction feels irrational',
                 'p' => ['Because it is. Attraction is driven by biology, survival instincts, emotional memory, subconscious pattern matching, and chemical reward — not logic. Humans do not fall for the "best" partner; they fall for the partner who activates the right neural circuits.']],
            ],
        ],
        [
            'slug' => 'attachment-styles',
            'title' => 'Attachment Styles in Attraction — Why We Want Who We Want',
            'takeaway' => 'Attachment styles shape who feels "safe," who feels "exciting," and who feels "dangerous but irresistible." They operate below conscious awareness, pulling us toward certain partners even when logic disagrees.',
            'sections' => [
                ['h' => 'Secure attachment — drawn to stability, warmth, reciprocity',
                 'p' => ['Securely attached people choose emotional consistency, healthy communication, reliability, and balanced intimacy. Comfortable with both closeness and independence, they do not chase chaos because their nervous system does not confuse intensity with love. Secure attachment creates the healthiest long-term relationships.']],
                ['h' => 'Anxious attachment — drawn to avoidant partners',
                 'p' => ['Driven by fear of abandonment, anxious individuals crave closeness and reassurance — yet are often attracted to emotionally unavailable, inconsistent, mixed-signal partners. Inconsistency creates dopamine spikes; the nervous system reads unpredictability as passion. Hence: "I know they\'re bad for me, but I can\'t stop thinking about them." The bond forms through fear plus desire, not stability.']],
                ['h' => 'Avoidant attachment — drawn to independence and intensity',
                 'p' => ['Avoidant individuals fear being controlled or engulfed. They gravitate toward mysterious, self-sufficient partners who do not demand emotional intimacy. The anxious-avoidant push-pull creates intensity, but avoidants struggle with vulnerability and often sabotage relationships that feel "too close."']],
                ['h' => 'Disorganized attachment — drawn to chaos and trauma chemistry',
                 'p' => ['Born of inconsistent or frightening early experiences, disorganized attachment craves closeness and fears it simultaneously. It is drawn to volatile, unpredictable partners and extreme highs and lows. The nervous system equates fear with excitement, chaos with passion, instability with love — producing the strongest "magnetic but destructive" relationships.']],
                ['h' => 'Why attachment beats logic',
                 'ul' => ['Familiarity: people are drawn to what feels familiar, even when unhealthy.', 'Neural pathways: attachment patterns are wired in childhood and repeat in adulthood.', 'The dopamine-anxiety loop: unpredictable partners spike dopamine harder than stable ones.', 'Fantasy projection: idealized fantasies attach to partners who activate old wounds.', 'Fear of change: rewiring attachment requires emotional risk and discomfort.'],
                 'p' => ['Attraction is not random. It is a neurobiological echo of childhood attachment patterns — people fall for the partner who fits their nervous system\'s blueprint.']],
            ],
        ],
        [
            'slug' => 'trauma-chemistry-vs-compatibility',
            'title' => 'Trauma Chemistry vs Real Compatibility',
            'takeaway' => 'Trauma chemistry feels like destiny — fast, overwhelming, magnetic — but it is your nervous system reenacting old wounds. Real compatibility feels calmer and safer, which is why many people mistake it for "boring."',
            'sections' => [
                ['h' => 'Trauma chemistry — attraction based on wounds',
                 'p' => ['It fires when someone activates unresolved emotional patterns: unpredictability, hot-and-cold behavior, emotional unavailability, mixed signals, power imbalance, high-conflict-high-passion cycles, feeling you must earn love. The amygdala and dopamine system fire together; danger reads as excitement; familiar dysfunction feels like home.'],
                 'ul' => ['What it produces: obsession, anxiety, rumination, jealousy, emotional dependency, breakup-and-reunion cycles.', '"I can\'t quit this person" means your nervous system is hooked — not that the relationship is healthy.']],
                ['h' => 'Real compatibility — attraction based on safety and alignment',
                 'p' => ['Real compatibility activates the parasympathetic nervous system — calm, trust, connection. It is built from emotional consistency, clear communication, shared values, mutual respect, secure attachment, and emotional availability.'],
                 'ul' => ['It feels like: "I can breathe around this person." "I feel understood." "I don\'t have to perform."', 'No adrenaline spikes, no guessing games, no rollercoaster. Secure bonding, not trauma bonding.']],
                ['h' => 'The core differences',
                 'ul' => ['Trauma chemistry: fast, intense, addictive, unpredictable, anxiety-driven — feels like "I need them," creates chaos, repeats childhood patterns.', 'Real compatibility: slow, steady, trust-building, predictable, calm — feels like "I choose them," creates safety, builds a future.']],
                ['h' => 'Why trauma chemistry feels stronger',
                 'ul' => ['The brain mistakes intensity for importance.', 'Childhood wounds seek reenactment — the brain tries to resolve old pain by recreating it.', 'Intermittent reward is the most addictive pattern known to neuroscience.', 'The nervous system prefers familiar pain over unfamiliar peace.', 'Real compatibility lacks drama — and people raised in chaos read calm as boredom.']],
                ['h' => 'How to tell which one you are in',
                 'ul' => ['Trauma chemistry: anxious more than happy, afraid of losing them, can\'t think clearly, addicted to their attention, tolerating disrespect, hoping they\'ll change.', 'Real compatibility: calm, valued, seen, respected, emotionally safe, communicating openly, growing together.'],
                 'p' => ['Trauma chemistry is a cycle. Compatibility is a choice.']],
            ],
        ],
        [
            'slug' => 'override-destructive-patterns',
            'title' => 'How to Override Destructive Attraction Patterns',
            'takeaway' => 'You override destructive attraction patterns by retraining your nervous system. Trauma chemistry is a body-level reaction, not a conscious choice — so the fix must target the body, the brain, and the patterns pulling you toward the wrong people.',
            'sections' => [
                ['h' => '1. Name the pattern',
                 'p' => ['Anxious chases avoidant; avoidant chooses unavailable; the fixer chooses broken partners; the people-pleaser chooses takers. Your nervous system is repeating what it learned early. Naming the pattern is the first step to breaking it.']],
                ['h' => '2. Slow down the timeline',
                 'p' => ['Trauma chemistry thrives on speed: fast bonding, fast intimacy, fast emotional merging. Slowing down exposes red flags, incompatibility, immaturity, and fantasy projection. Slow the pace and destructive partners lose their power — this is the principle SlowDating is built on.']],
                ['h' => '3. Shift from chemistry to compatibility',
                 'p' => ['Chemistry is a feeling; compatibility is a function. Do your values, lifestyles, communication styles, goals, and emotional needs align? If not, chemistry is irrelevant.']],
                ['h' => '4. Rewire the nervous system',
                 'p' => ['The body gets addicted to adrenaline, cortisol, dopamine spikes, and intermittent reward. Mindfulness, somatic work, breathwork, slowed emotional responses, and steady partners teach the nervous system that calm is safe — not boring.']],
                ['h' => '5. Break the intermittent reinforcement cycle',
                 'p' => ['Unpredictable partners create the same addiction mechanics as slot machines. Stop chasing, stop waiting for the "good moment," stop rewarding inconsistency, stop granting second chances for the same behavior. Consistency is the antidote.']],
                ['h' => '6. Choose calm over intense',
                 'p' => ['Healthy attraction feels like clarity, comfort, safety, and steady connection. Destructive attraction feels like anxiety, obsession, confusion, and adrenaline. Your body has to learn to prefer the first.']],
                ['h' => '7. Replace fantasy with reality',
                 'p' => ['"They\'ll change." "They\'re just scared." "It\'s complicated." Reality is simpler: are they consistent, available, respectful, and aligned with your life? Fantasy is the enemy of healthy love.']],
                ['h' => '8. Heal the original wound, then build a new template',
                 'p' => ['Patterns rooted in abandonment, neglect, or past betrayal repeat until addressed. Then practice attraction to kindness, stability, maturity, reliability, and mutual effort. At first it will feel "too calm." Later it will feel like home.'],
                 'ul' => ['You don\'t override these patterns by thinking differently — you override them by feeling differently.', 'Trauma chemistry feels like destiny. Compatibility feels like peace. Choose peace.']],
            ],
        ],
        [
            'slug' => 'slow-burn-lasts-longer',
            'title' => 'Why Slow-Burn Relationships Last Longer',
            'takeaway' => 'Slow-burn relationships last because they build attachment, trust, and shared identity gradually — bonding the nervous system through safety instead of trauma chemistry.',
            'sections' => [
                ['h' => '1. Gradual dopamine, not the addictive rollercoaster',
                 'p' => ['Fast relationships run on dopamine spikes — thrilling, and quickly burned out. Slow ones produce steady dopamine: long-term motivation, sustained interest, emotional stability, deeper bonding. For attachment, the brain prefers consistency over chaos.']],
                ['h' => '2. Oxytocin-based bonding — trust grows instead of exploding',
                 'p' => ['Oxytocin accumulates through repeated conversations, shared experiences, vulnerability, and small acts of care — building trust, loyalty, and safety. Fast relationships skip this and substitute intensity for intimacy.']],
                ['h' => '3. Calm is connection',
                 'p' => ['Slow relationships activate the parasympathetic nervous system — calm, comfort, clarity: the foundation of secure attachment. Fast ones activate the stress system — anxiety, obsession, adrenaline — which people mistake for passion.']],
                ['h' => '4. Time reveals compatibility',
                 'p' => ['Conflict style, communication habits, emotional maturity, lifestyle, values, and goals are invisible in week one. Slow relationships let incompatibilities surface before commitment; fast ones commit first and discover later.']],
                ['h' => '5. Fantasy fades, reality emerges',
                 'p' => ['Early attraction is projection: "they\'re perfect," "this is destiny." Slow pacing lets the fantasy fade and reality appear. If the connection survives reality, it is strong. If it collapses when fantasy fades, it was never real.']],
                ['h' => '6. Intimacy and shared identity grow naturally',
                 'p' => ['Shared stories, vulnerability, consistency, and mutual investment create deep emotional connection — the strongest predictor of long-term success. Over time partners build shared routines, memories, goals, and meaning. Fast relationships skip this and collapse under stress.'],
                 'ul' => ['Fast relationships feel like fireworks. Slow relationships feel like sunrise.', 'Fireworks burn out. Sunrises build a day.']],
            ],
        ],
        [
            'slug' => 'identify-compatibility-early',
            'title' => 'How to Identify Real Compatibility Early',
            'takeaway' => 'You identify real compatibility early by watching patterns, not feelings. Chemistry misleads; consistency, communication, values, and emotional safety reveal whether a relationship can last.',
            'sections' => [
                ['h' => '1. Emotional safety — the #1 predictor',
                 'p' => ['You don\'t feel judged; you can express needs without fear; they listen without defensiveness; disagreements don\'t escalate. If you feel relief instead of tension around someone, that is compatibility.']],
                ['h' => '2. Consistency — the antidote to trauma chemistry',
                 'p' => ['Consistent communication, effort, emotional tone, respect, and follow-through. Inconsistent people create intensity; consistent people create longevity.']],
                ['h' => '3. Aligned values — the backbone',
                 'p' => ['Values determine lifestyle, priorities, conflict style, parenting, money, and moral compass. Revealing early questions: how do they treat people who can\'t benefit them? How do they handle stress? What counts as "success" to them? Values matter more than personality.']],
                ['h' => '4. Communication style — the hidden dealbreaker',
                 'p' => ['Clarity vs vagueness, openness vs avoidance, honesty vs defensiveness, curiosity vs judgment. If communication feels easy early, it will feel easy later.']],
                ['h' => '5. Shared pace and lifestyle',
                 'p' => ['Real compatibility means moving at the same speed — no one rushing, no one dragging. And lifestyle is daily reality: sleep, work, social habits, ambition, money behavior, health. If lifestyles clash, chemistry won\'t save you.']],
                ['h' => '6. Conflict compatibility — the most overlooked sign',
                 'p' => ['You don\'t need a fight to see conflict style — watch minor frustrations, misunderstandings, and boundaries. Healthy conflict looks like curiosity, calmness, repair, accountability. Unhealthy looks like blame, withdrawal, escalation, stonewalling. Conflict style predicts longevity better than attraction.']],
                ['h' => '7. Attachment fit and mutual effort',
                 'p' => ['Mismatch feels like chasing, performing, guessing, waiting. Fit feels like calm, secure, seen, valued. And attraction is easy — effort is compatibility: equal initiation, planning, vulnerability, and investment. If effort is one-sided early, it will be one-sided forever.'],
                 'ul' => ['Chemistry is a spark. Compatibility is the structure.', 'One fades. The other lasts.']],
            ],
        ],
        [
            'slug' => 'slow-relationship-chemistry',
            'title' => 'How Slow Relationships Build Deeper Chemistry',
            'takeaway' => 'Slow-developing relationships create stronger, more sustainable chemistry because the nervous system bonds through trust, safety, anticipation, and emotional intimacy — not adrenaline, anxiety, or novelty.',
            'sections' => [
                ['h' => '1. Safety first, desire second',
                 'p' => ['When a relationship grows slowly, the brain layers oxytocin (bonding), dopamine (pleasure), serotonin (stability), and endorphins (comfort) into a foundation of emotional safety — the strongest predictor of long-term physical satisfaction. Fast relationships run on adrenaline, novelty, anxiety, and fantasy, which fade.']],
                ['h' => '2. Anticipation builds desire',
                 'p' => ['Anticipation is one of the most powerful accelerators of attraction. Slow relationships create curiosity, mystery, emotional buildup, and progressive closeness — activating the reward system more strongly than instant gratification. The longer the anticipation, the stronger the eventual chemistry.']],
                ['h' => '3. Emotional intimacy fuels physical intimacy',
                 'p' => ['Shared stories, vulnerability, trust, and mutual understanding grow first. When physical intimacy arrives, it carries emotional meaning and psychological closeness — making the connection richer and more enduring.']],
                ['h' => '4. Secure attachment improves everything',
                 'p' => ['A relaxed nervous system, open communication, and comfort with vulnerability dramatically improve connection, because both partners feel safe, valued, and understood. Fast relationships often activate anxious or avoidant patterns that erode chemistry over time.']],
                ['h' => '5. Desire built on knowing beats desire built on fantasy',
                 'p' => ['Fast relationships idealize and project. Slow ones desire the real person — how they think, feel, communicate, and connect. Desire built on reality is far more stable.']],
                ['h' => '6. Chemistry becomes multidimensional',
                 'p' => ['Emotional, intellectual, lifestyle, humor, and shared-experience connection layer together into a desire that is resilient to stress, aging, routine, and life changes. Intimacy becomes communication, not performance — connected, responsive, attuned, mutual.'],
                 'ul' => ['Fast relationships create intensity. Slow relationships create depth.']],
            ],
        ],
    ];
}

$articles = smart_dating_articles();

if (($_GET['format'] ?? '') === 'json') {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($articles, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

$slug = (string) ($_GET['article'] ?? '');
$current = null;
$currentIndex = -1;
foreach ($articles as $i => $article) {
    if ($article['slug'] === $slug) {
        $current = $article;
        $currentIndex = $i;
        break;
    }
}

sd_page_open('Smart Dating', 'SlowDating · the science of choosing well');
?>
<style>
    .takeaway { background: #262030; border-left: 4px solid #ff9cc0; border-radius: 0 12px 12px 0; padding: 12px 16px; color: #eadff0; margin: 10px 0 4px; }
    .takeaway strong { color: #ffc4da; letter-spacing: .08em; font-size: 12px; text-transform: uppercase; display: block; margin-bottom: 4px; }
    article h2 { margin-top: 4px; }
    article h3 { font-size: 16px; color: #ffc4da; margin: 20px 0 6px; }
    article p { max-width: 68ch; }
    article ul { max-width: 66ch; }
    .art-nav { display: flex; flex-wrap: wrap; gap: 10px 18px; margin-top: 16px; }
</style>

<?php if ($current === null): ?>
    <p style="max-width:70ch">Chemistry is a spark; compatibility is the structure. These articles explain the science behind
        SlowDating's design — why the strongest first attractions so often fail, what your brain is actually doing,
        and why relationships that grow slowly hold. Nine short reads, each self-contained.</p>
    <?php foreach ($articles as $i => $article): ?>
        <section>
            <h2 style="margin:0 0 6px"><a href="?article=<?= sd_e($article['slug']) ?>" style="color:#f3eef6;text-decoration:none"><?= $i + 1 ?>. <?= sd_e($article['title']) ?></a></h2>
            <p style="margin:0 0 10px"><?= sd_e($article['takeaway']) ?></p>
            <a href="?article=<?= sd_e($article['slug']) ?>">Read the article →</a>
        </section>
    <?php endforeach; ?>
<?php else: ?>
    <article>
        <p><a href="smart-dating.php">← All Smart Dating articles</a></p>
        <section>
            <h2><?= sd_e($current['title']) ?></h2>
            <div class="takeaway"><strong>Concise takeaway</strong><?= sd_e($current['takeaway']) ?></div>
            <?php foreach ($current['sections'] as $section): ?>
                <h3><?= sd_e($section['h']) ?></h3>
                <?php foreach ((array) ($section['p'] ?? []) as $paragraph): ?>
                    <p><?= sd_e($paragraph) ?></p>
                <?php endforeach; ?>
                <?php if (!empty($section['ul'])): ?>
                    <ul>
                        <?php foreach ($section['ul'] as $item): ?>
                            <li><?= sd_e($item) ?></li>
                        <?php endforeach; ?>
                    </ul>
                <?php endif; ?>
            <?php endforeach; ?>
        </section>
        <div class="art-nav">
            <?php if ($currentIndex > 0): ?>
                <a href="?article=<?= sd_e($articles[$currentIndex - 1]['slug']) ?>">← <?= sd_e($articles[$currentIndex - 1]['title']) ?></a>
            <?php endif; ?>
            <?php if ($currentIndex < count($articles) - 1): ?>
                <a href="?article=<?= sd_e($articles[$currentIndex + 1]['slug']) ?>"><?= sd_e($articles[$currentIndex + 1]['title']) ?> →</a>
            <?php endif; ?>
        </div>
    </article>
<?php endif; ?>

<?php sd_page_close(); ?>
