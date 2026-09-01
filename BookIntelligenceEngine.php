<?php

declare(strict_types=1);

/**
 * Book Intelligence Studio
 *
 * A deterministic, dependency-free implementation of the five analysis
 * modules described in the product architecture. It is intentionally built
 * around explicit heuristics so a production app can later replace each
 * adapter with live research providers without changing the output contract.
 */
final class BookIntelligenceEngine
{
    private const WORDS_PER_PAGE = 250;

    private const STOP_WORDS = [
        'a', 'an', 'and', 'at', 'by', 'for', 'from', 'in', 'into', 'of',
        'on', 'or', 'the', 'to', 'with', 'your', 'how', 'why', 'what',
    ];

    public function buildKit(string $topic, array $options = []): array
    {
        $topic = $this->normalizeTopic($topic);

        if ($topic === '') {
            throw new InvalidArgumentException('A topic is required.');
        }

        $topicAnalysis = $this->analyzeTopic($topic, $options);
        $competition = $this->scanCompetition(
            $topic,
            is_array($options['competitors'] ?? null) ? $options['competitors'] : [],
        );
        $blueprint = $this->generateBlueprint($topic, $topicAnalysis, $competition);
        $media = $this->optimizeMedia($topic, $topicAnalysis, $competition, $blueprint);
        $probability = $this->calculateProbability(
            $topicAnalysis,
            $competition,
            $blueprint,
            $media,
            $options,
        );

        return [
            'meta' => [
                'topic' => $topic,
                'generated_at' => gmdate(DATE_ATOM),
                'engine_version' => '1.0',
                'disclaimer' => 'Scores are directional planning estimates, not sales guarantees.',
            ],
            'topic_analysis' => $topicAnalysis,
            'competition' => $competition,
            'blueprint' => $blueprint,
            'media' => $media,
            'probability' => $probability,
            'kit' => $this->kitSummary($topic, $topicAnalysis, $competition, $blueprint, $media, $probability),
        ];
    }

    public function analyzeTopic(string $topic, array $options = []): array
    {
        $signals = $this->signals($topic);
        $audience = $this->audienceProfile($topic, $signals);
        $trend = $signals['trend'];
        $evergreen = $signals['evergreen'];

        $demand = $this->clamp(
            38 + ($signals['specificity'] * 18) + ($trend * 0.26) + ($signals['social'] * 0.16),
            0,
            100,
        );
        $longevity = $this->clamp(
            42 + ($evergreen * 0.48) + ($signals['academic'] * 0.18) - ($trend * 0.08),
            0,
            100,
        );

        $angles = [
            $this->angleFor($topic, $signals, 'practical'),
            $this->angleFor($topic, $signals, 'contrarian'),
            $this->angleFor($topic, $signals, 'human'),
        ];

        return [
            'scores' => [
                'topic_demand' => $this->score($demand),
                'topic_longevity' => $this->score($longevity),
                'market_momentum' => $this->score(($trend + $signals['social']) / 2),
            ],
            'audience_size_estimate' => $this->audienceEstimate($demand, $audience),
            'reader_persona' => $audience,
            'trend_status' => $trend >= 72 ? 'Rising' : ($trend >= 48 ? 'Steady interest' : 'Emerging'),
            'evergreen_status' => $evergreen >= 68 ? 'Evergreen foundation' : 'Trend-sensitive opportunity',
            'best_angles' => $angles,
            'signal_notes' => [
                'Search intent is strongest when the promise is specific and actionable.',
                'Readers in this space reward examples, clear frameworks, and visible evidence.',
                $evergreen >= 68
                    ? 'The core question has staying power beyond the current news cycle.'
                    : 'Pair the timely hook with durable principles to protect the long tail.',
            ],
        ];
    }

    public function scanCompetition(string $topic, array $competitors = []): array
    {
        $signals = $this->signals($topic);
        $seedTitles = [
            $topic . ': The Complete Guide',
            'The New Rules of ' . ucwords($topic),
            'Mastering ' . ucwords($topic),
            'Inside ' . ucwords($topic),
        ];
        $titles = array_values(array_filter(array_merge($competitors, $seedTitles), static fn ($title): bool => is_string($title) && trim($title) !== ''));
        $titles = array_slice(array_values(array_unique(array_map('trim', $titles))), 0, 8);

        $rivals = [];
        foreach ($titles as $index => $title) {
            $depth = $this->clamp(54 + (($signals['specificity'] * 22) - ($index * 2)), 34, 88);
            $media = $this->clamp(31 + ($signals['social'] * 0.4) + (($index % 3) * 7), 24, 84);
            $citations = $this->clamp(45 + ($signals['academic'] * 0.36) - (($index % 2) * 6), 28, 86);
            $rivals[] = [
                'title' => $title,
                'editorial_depth' => $this->score($depth),
                'media_richness' => $this->score($media),
                'citation_strength' => $this->score($citations),
                'reader_reaction' => $index % 2 === 0 ? 'Useful but dense' : 'Accessible, light on evidence',
                'observed_gap' => $index % 2 === 0
                    ? 'Limited visual explanation and few guided exercises'
                    : 'Strong narrative, but weak source trail and practical follow-through',
            ];
        }

        $gap = $this->clamp(58 + ($signals['specificity'] * 18) + ($signals['academic'] * 0.12), 0, 100);
        $opportunities = [
            'Own the bridge between credible research and a reader-friendly action plan.',
            'Use case studies that reveal decisions, trade-offs, and outcomes—not just anecdotes.',
            'Make the invisible parts of the topic visible through diagrams and annotated examples.',
        ];

        return [
            'rival_count' => count($rivals),
            'rivals' => $rivals,
            'scores' => [
                'competitive_gap' => $this->score($gap),
                'content_opportunity' => $this->score($this->clamp($gap + 7, 0, 100)),
                'media_opportunity' => $this->score($this->clamp($gap + 13, 0, 100)),
            ],
            'what_rivals_do_well' => [
                'They make the category legible through familiar language and recognizable examples.',
                'They package a complex question into a promise that is easy to repeat.',
            ],
            'what_readers_want_more_of' => [
                'A sharper point of view instead of a neutral information dump.',
                'Practical sequences readers can try, teach, or return to.',
                'Evidence that is visible in the flow of the story.',
            ],
            'opportunities' => $opportunities,
            'weakness_exploitation_plan' => [
                'Lead with a distinct promise that names the reader and the transformation.',
                'Turn every major claim into a proof moment: source, story, visual, or exercise.',
                'Create a companion layer of media so the book is easier to understand and share.',
            ],
        ];
    }

    public function generateBlueprint(string $topic, array $topicAnalysis, array $competition): array
    {
        $angle = $topicAnalysis['best_angles'][0]['title'] ?? 'The practical path through ' . $topic;

        return [
            'positioning' => [
                'working_title' => $this->titleCase($topic) . ': A Field Guide for People Who Want to Go Deeper',
                'core_promise' => $angle,
                'editorial_thesis' => 'Make the reader feel more capable after every chapter by pairing context with a next move.',
            ],
            'chapters' => $this->suggestTableOfContents(
                $topic,
                (string) ($topicAnalysis['reader_persona']['primary'] ?? 'the reader'),
                $angle,
            ),
            'foundational_overview_plan' => 'Open with a one-page map, a plain-language glossary, and a “why this matters now” frame.',
            'context_background_plan' => 'Keep background modular: short timelines, annotated sidebars, and optional deep dives.',
            'case_study_integration_plan' => 'Include one close-read case study per major idea, with a before / decision / result structure.',
            'instructional_framework_plan' => [
                'Name the principle.',
                'Show it in a real situation.',
                'Give the reader a small action.',
                'Offer a reflection prompt and a way to measure progress.',
            ],
            'citation_strategy' => [
                'Use primary research and original reporting for high-stakes claims.',
                'Place source cues near the claim, then collect full notes in a clean reference layer.',
                'Label estimates, interpretation, and established evidence differently.',
            ],
            'editorial_quality_plan' => [
                'Every chapter earns its place with one central question.',
                'Alternate explanation, story, visual, and practice to maintain momentum.',
                'End each chapter with a “use this tomorrow” recap.',
            ],
            'recommended_angle' => $angle,
            'competitive_gap_to_fill' => $competition['opportunities'][0] ?? 'Connect evidence to action.',
        ];
    }

    /**
     * Generate a suggested table of contents that can be edited before drafting.
     *
     * @return array<int, array{number:int, title:string, purpose:string, detail:string}>
     */
    public function suggestTableOfContents(string $topic, string $audience = '', string $promise = ''): array
    {
        $topic = $this->normalizeTopic($topic);
        if ($topic === '') {
            throw new InvalidArgumentException('A topic is required to suggest a table of contents.');
        }

        if ($this->isTeenJobsTopic($topic)) {
            return $this->teenJobsTableOfContents();
        }
        if ($this->isApproachTopic($topic)) {
            return $this->approachTableOfContents();
        }

        $audience = $this->normalizeTopic($audience) ?: 'the reader';
        $promise = $this->normalizeTopic($promise) ?: 'understand the topic and make a better decision';
        $topicLabel = $this->titleCase($topic);
        $topicLower = strtolower($topic);

        if ($this->isSocialTopic($topic)) {
            // Social-science books document people and their behavior:
            // establish the current state of affairs, contrast it with the
            // past, deconstruct the origins of the change, support the
            // account with evidence, and propose solutions — never "systems".
            return [
                ['number' => 1, 'title' => 'The State of Affairs Today', 'purpose' => 'Document the current state of the phenomenon', 'detail' => 'Open with what ordinary people see every day about ' . $topicLower . ', put honest numbers behind the anecdotes, show who is living with the consequences right now, and explain why the question can no longer be waved away.'],
                ['number' => 2, 'title' => 'How It Used to Be', 'purpose' => 'Contrast the present with the world before the change', 'detail' => 'Recreate the customs, expectations, and unwritten rules earlier generations lived by, show how those arrangements actually worked day to day, give credit for what they got right, and be honest about what they got wrong.'],
                ['number' => 3, 'title' => 'The Turning Points', 'purpose' => 'Deconstruct the origins: the events that changed everything', 'detail' => 'Move era by era through the wars, laws, movements, and inventions that remade ' . $topicLower . ', show what each turning point changed in real households, and trace how the changes compounded into the world we have now.'],
                ['number' => 4, 'title' => 'Who Gained and Who Lost', 'purpose' => 'Deconstruct the origins: the interests behind the change', 'detail' => 'Identify who benefited from the new arrangements and who paid for them, resist the temptation to declare simple villains, follow the money and the status where they moved, and show why both winners and losers often misread each other.'],
                ['number' => 5, 'title' => 'How It Plays Out in Daily Life', 'purpose' => 'Show the causes operating in ordinary days', 'detail' => 'Follow the change into kitchens, workplaces, and neighborhoods, show real people making the small choices that add up to ' . $topicLower . ', and let the reader recognize scenes from their own life in the pattern.'],
                ['number' => 6, 'title' => 'The Stories Each Side Tells', 'purpose' => 'Deconstruct the competing explanations in their own voices', 'detail' => 'Lay out the explanations people give for ' . $topicLower . ' through composite stories and reported conversations, let each side make its best case in its own words, test each story against the strongest evidence available, and keep only the claims a fair reader can defend.'],
                ['number' => 7, 'title' => 'What the Evidence Shows', 'purpose' => 'Support the account with data', 'detail' => 'Assemble the surveys, statistics, and long-running studies that bear on ' . $topicLower . ', show how the trend lines moved decade by decade, be candid about what the data cannot settle, and give readers numbers they can quote with confidence.'],
                ['number' => 8, 'title' => 'What It Costs Us', 'purpose' => 'Count the human consequences', 'detail' => 'Tally the price paid by individuals, families, and communities, connect the private pain to the public statistics, show the costs that never make the news, and explain why everyone has a stake in the outcome.'],
                ['number' => 9, 'title' => 'What\'s Been Tried', 'purpose' => 'Weigh the fixes already attempted', 'detail' => 'Review the programs, movements, and personal experiments already aimed at ' . $topicLower . ', be honest about which ones failed and why, profile the people and communities quietly bucking the trend, and show what the exceptions reveal about the rule.'],
                ['number' => 10, 'title' => 'The Way Forward', 'purpose' => 'Propose solutions the reader can act on', 'detail' => 'Draw the lessons of the history into practical terms, propose what individuals and communities can actually do, name what must be accepted because it will not reverse, and end with a vision ' . $audience . ' can act on.'],
            ];
        }

        return [
            ['number' => 1, 'title' => 'The Question Beneath ' . $topicLabel, 'purpose' => 'Earn attention and establish the stakes', 'detail' => 'Open with the tension this book resolves for ' . $audience . ', show what changes once readers ' . strtolower($promise) . ', name the real cost of leaving the question unanswered, and preview the road the book will travel.'],
            ['number' => 2, 'title' => 'Where ' . $topicLabel . ' Came From', 'purpose' => 'Ground the reader in the essential history', 'detail' => 'Trace the origins and turning points that created the present landscape, walk through the key eras and what each one changed, separate durable facts from comfortable folklore, and show why the past still steers what happens today.'],
            ['number' => 3, 'title' => 'The Forces at Work', 'purpose' => 'Turn complexity into a usable explanation', 'detail' => 'Explain the moving parts and pressures behind ' . $topicLower . ', map the incentives of every major player, expose the constraints none of them can escape, and leave readers one memorable explanation they can retell from memory.'],
            ['number' => 4, 'title' => 'What Everyone Gets Wrong', 'purpose' => 'Clear away the myths so the truth can land', 'detail' => 'Take the most common beliefs about ' . $topicLower . ', test each one against the strongest available evidence, explain why the appealing myths survive, and replace them with claims a careful reader can defend.'],
            ['number' => 5, 'title' => 'The Decisions That Change Outcomes', 'purpose' => 'Make the argument credible through proof', 'detail' => 'Build the center of the book around three to five case studies that show context, choice, trade-off, and result.'],
            ['number' => 6, 'title' => 'A Framework for Practice', 'purpose' => 'Move from insight to action', 'detail' => 'Give readers a repeatable loop: diagnose the situation, choose a move, run a small test, and learn from the result.'],
            ['number' => 7, 'title' => 'When It Goes Wrong', 'purpose' => 'Prepare readers for the predictable failures', 'detail' => 'Catalog the most common mistakes and traps around ' . $topicLower . ', show the early warning signs of each one, explain how to recover once a plan breaks, and turn the failure stories into reusable lessons.'],
            ['number' => 8, 'title' => 'What Happens Next', 'purpose' => 'Create a durable ending', 'detail' => 'Close with future implications, a short reader toolkit, and a way to keep applying the book as the category changes.'],
        ];
    }

    /**
     * The Nonfiction Outline Editor: an editorial agent that reviews any
     * table of contents against the social-science documentation method —
     * current state, contrast with the past, deconstructed origins,
     * supporting evidence, and proposed solutions.
     *
     * @param array<int, array<string, mixed>> $chapters Rows with title/purpose/detail.
     * @return array<string, mixed>
     */
    public function reviewOutline(string $topic, array $chapters): array
    {
        $titles = array_map(static fn (array $c): string => (string) ($c['title'] ?? ''), $chapters);
        $all = array_map(
            static fn (array $c): string => strtolower(((string) ($c['title'] ?? '')) . ' ' . ((string) ($c['purpose'] ?? '')) . ' ' . ((string) ($c['detail'] ?? ''))),
            $chapters,
        );
        $count = count($chapters);
        $social = $this->isSocialTopic($topic) || $this->isApproachTopic($topic);
        $matches = static function (array $rows, string $pattern): bool {
            foreach ($rows as $row) {
                if (preg_match($pattern, $row) === 1) {
                    return true;
                }
            }
            return false;
        };

        $checks = [];
        $suggest = [];
        $opener = $all[0] ?? '';
        $closerWindow = array_slice($all, -2);
        $checks[] = ['id' => 'present-state-opener', 'label' => $social ? 'Opens by documenting the current state of affairs' : 'Opens by establishing the stakes', 'passed' => preg_match($social ? '/\btoday|current|now\b|state of|vanish|notice|these days|right now/' : '/\btoday|current|now\b|state of|question|stakes|matter|more than|why\b/', $opener) === 1];
        $checks[] = ['id' => 'past-contrast', 'label' => 'Contrasts the present with the past', 'passed' => $matches($all, '/used to|before|old order|history|earlier generations|decades|the past|era by era/')];
        $checks[] = ['id' => 'origins-deconstructed', 'label' => 'Deconstructs the origins of the change', 'passed' => $matches($all, '/turning point|war|revolution|movement|origin|cause|what changed|rupture/')];
        $checks[] = ['id' => 'evidence-support', 'label' => 'Supports the account with evidence', 'passed' => $matches($all, '/evidence|data|numbers|survey|statistic|studies|cost|price|document/')];
        $checks[] = ['id' => 'solutions-closer', 'label' => $social ? 'Closes by proposing solutions' : 'Closes with next steps the reader can take', 'passed' => $matches($closerWindow, $social ? '/forward|solution|relearn|way back|truce|practice|\bwhat\b.*\bcan\b.*\bdo\b|path|heal/' : '/forward|solution|next|toolkit|tools|step|path|apply/')];
        $checks[] = ['id' => 'human-actors', 'label' => 'Chapters are about people and their behavior', 'passed' => $matches($all, '/\b(men|women|people|families|readers|parents|children|couples|communities|workers|voices)\b/')];
        $abstractTitles = array_values(array_filter($titles, static fn (string $t): bool => preg_match('/\b(system|framework|model|overview|module|paradigm)\b/i', $t) === 1));
        $checks[] = ['id' => 'concrete-titles', 'label' => $social ? 'Titles name eras, events, and actors — not systems or frameworks' : 'Titles stay concrete', 'passed' => !$social || $abstractTitles === []];
        $checks[] = ['id' => 'chapter-count', 'label' => 'Enough chapters to sustain a book (8–30)', 'passed' => $count >= 8 && $count <= 30];
        $thinDetails = 0;
        foreach ($chapters as $chapter) {
            if (mb_strlen(trim((string) ($chapter['detail'] ?? ''))) < 80) {
                $thinDetails++;
            }
        }
        $checks[] = ['id' => 'substantive-details', 'label' => 'Every chapter brief is substantive enough to draft from', 'passed' => $thinDetails === 0];
        $checks[] = ['id' => 'no-duplicate-titles', 'label' => 'No two chapters cover the same ground', 'passed' => count(array_unique(array_map('strtolower', $titles))) === $count];
        $lastCost = -1;
        $firstSolution = PHP_INT_MAX;
        foreach ($all as $i => $row) {
            if (preg_match('/\bcost|price|toll|consequence/', $row) === 1) {
                $lastCost = $i;
            }
            if ($firstSolution === PHP_INT_MAX && preg_match('/forward|solution|relearn|way back|truce|\bwhat\b.*\bcan\b.*\bdo\b|repair|heal/', $row) === 1) {
                $firstSolution = $i;
            }
        }
        $checks[] = ['id' => 'costs-before-solutions', 'label' => 'Counts the costs before proposing the cures', 'passed' => $lastCost === -1 || $firstSolution === PHP_INT_MAX || $lastCost <= $firstSolution || $firstSolution > (int) ($count * 0.6)];
        $longTitles = array_values(array_filter($titles, static fn (string $t): bool => mb_strlen($t) > 60));
        $checks[] = ['id' => 'title-economy', 'label' => 'Titles stay short enough to remember (≤60 characters)', 'passed' => $longTitles === []];

        foreach ($checks as $check) {
            if ($check['passed']) {
                continue;
            }
            $suggest[] = match ($check['id']) {
                'present-state-opener' => 'Open with a chapter that documents the state of affairs today, so the reader sees the phenomenon before the explanation.',
                'past-contrast' => 'Add a chapter that recreates how things used to be — the contrast with the past is what makes the change visible.',
                'origins-deconstructed' => 'Add chapters that deconstruct the origins: the wars, laws, movements, and inventions that caused the change.',
                'evidence-support' => 'Add a chapter that supports the account with surveys, statistics, and documented costs.',
                'solutions-closer' => 'End by proposing solutions the reader can act on, not just a summary.',
                'human-actors' => 'Recenter the chapters on people and their behavior — social books are about actors, not mechanisms.',
                'concrete-titles' => 'Rewrite these abstract titles with concrete eras, events, or actors: ' . implode('; ', $abstractTitles) . '.',
                'chapter-count' => $count < 8 ? 'Split the big causal factors into their own chapters — a full book needs at least eight.' : 'Merge overlapping chapters — past thirty, chapters stop earning their place.',
                'substantive-details' => 'Flesh out the thin chapter briefs — each needs enough concrete instruction to draft a full chapter from.',
                'no-duplicate-titles' => 'Rename or merge the chapters that repeat a title.',
                'costs-before-solutions' => 'Move the costs and consequences ahead of the solutions — readers need to feel the stakes before the cures.',
                'title-economy' => 'Shorten these titles to something a reader can remember: ' . implode('; ', $longTitles) . '.',
                default => 'Revisit this chapter plan.',
            };
        }

        $passed = count(array_filter($checks, static fn (array $c): bool => (bool) $c['passed']));
        $score = $count === 0 ? 0 : (int) round(($passed / count($checks)) * 100);

        return [
            'agent' => [
                'name' => 'The Nonfiction Outline Editor',
                'mission' => 'Reviews every table of contents against the social-science method: document the present, contrast the past, deconstruct the origins, support with evidence, and propose solutions.',
            ],
            'genre' => $social ? 'social' : 'practical',
            'chapter_count' => $count,
            'score' => $score,
            'verdict' => $score >= 90 ? 'Ready to draft' : ($score >= 70 ? 'Strong, with gaps to close' : 'Needs restructuring'),
            'checks' => $checks,
            'suggestions' => $suggest,
        ];
    }

    /**
     * Detect social and cultural topics, which read as narrated history
     * rather than how-to instruction.
     */
    private function isSocialTopic(string $topic): bool
    {
        $t = ' ' . strtolower($topic) . ' ';
        if (str_starts_with(trim($t), 'why ')) {
            return true;
        }
        foreach (['men', 'women', 'man', 'woman', 'people', 'society', 'culture', 'marriage', 'dating', 'family', 'families', 'love', 'friendship', 'community', 'church', 'religion', 'generation', 'parents', 'children', 'america', 'loneliness', 'divorce', 'gender', 'masculinity', 'femininity', 'courtship', 'relationships'] as $keyword) {
            if (str_contains($t, ' ' . $keyword . ' ')) {
                return true;
            }
        }
        return false;
    }

    /** Detect books about why men no longer approach or court women. */
    private function isApproachTopic(string $topic): bool
    {
        $t = strtolower($topic);
        return str_contains($t, 'approach') && (str_contains($t, 'women') || str_contains($t, 'woman'));
    }

    /**
     * A curated, historically sequenced outline for "Why Men Don't Approach Women".
     *
     * @return array<int, array{number:int, title:string, purpose:string, detail:string}>
     */
    private function approachTableOfContents(): array
    {
        $chapters = [
            ['The Vanishing Approach', 'Establish the phenomenon and its stakes', 'Document how rarely men now initiate in person, how couples increasingly meet only through screens, how many young men report never approaching a woman at all, and why the question matters to women as much as to men.'],
            ['A Date Through the Decades: 1950 to 2026', 'Contrast one ordinary date across eight eras', 'Follow the same evening as it changes decade by decade: the 1950s soda-fountain date arranged by a call to the family telephone, the 1960s drive-in evening set free by the automobile, the 1970s disco and the new singles scene, the 1980s dinner-and-a-movie of the dating-handbook era, the 1990s office romance and the first online personals, the 2000s courtship conducted over text message, and the 2026 date that began with a swipe and a background search — noting in every era who asked, where they met, who paid, and what happened next.'],
            ['Two Courtships, Side by Side', 'Show real courtship and its modern abandonment through paired stories', 'Tell one full old-fashioned courtship — the introduction at a church social, calling on the family parlor, the handwritten letter, meeting her father, the six-month engagement — beside its modern counterpart: the app match, three weeks of texting, one coffee that goes nowhere, the slow fade of ghosting, and the situationship that never earns a name.'],
            ['Courtship in the Old Order: Before World War II', 'Show the traditional system this book measures change against', 'Describe pre-war gender relations built on clear scripts: the formal introduction and the family vetting, the dance card and the chaperoned social, the man as initiator and provider, marriage as an economic partnership, and manners as the currency that made approaching a stranger safe and legible.'],
            ['When the Men Went to War', 'Explain the first great rupture in the old order', 'Follow the Second World War as men shipped overseas, women filled factories and offices, first paychecks and bank accounts arrived in millions of women\'s names, and a taste of financial independence entered the culture that would never fully recede.'],
            ['The Home Without a Parent', 'Trace how family structure stopped teaching courtship', 'Examine the two-earner household and the latchkey childhood, the divorce revolution that removed fathers from daily life, sons who grew up with no model of how a man approaches a woman, and daughters raised on self-reliance rather than reliance.'],
            ['The Sexual Revolution Rewrites the Rules', 'Mark the collapse of the formal courtship script', 'Show how the pill, casual dating, and no-fault divorce dismantled the old sequence of courtship, replaced public rituals with private negotiation, promised freedom for both sexes, and quietly removed the instructions men had relied on for generations.'],
            ['Cheap Sex and the Devalued Approach', 'Explain why approaching lost its market logic', 'Follow the mating-market economics: when sex decoupled from commitment, the formal approach lost the leverage it once carried, courtship stopped being the price of companionship, and the men willing to do it stopped being rewarded for the effort.'],
            ['Chivalry on Trial', 'Examine how the feminist movement recast manners toward women', 'Explore how opening a door came to read as condescension, how paying the bill could be taken as an insult, how compliments became suspect, and how many men responded to the new uncertainty not by adapting but by opting out of gallantry altogether.'],
            ['Rivals, Not Partners', 'Explain the new competition between men and women', 'Look at classrooms and workplaces where the sexes now compete directly, men who feel threatened rather than attracted, the retreat many men beat from powerful and intelligent women, and the quiet resentment that competition breeds on both sides.'],
            ['The Paycheck Gap Flips', 'Ground the rivalry in the economic record', 'Chart women out-graduating men on every campus, young women out-earning young men in the big cities, male wages stagnant since the 1970s, and what it does to the old provider script when she no longer needs what he was raised to offer.'],
            ['The Provider Nobody Ordered', 'Show why traditional roles now repel the women they once won', 'Contrast young women who want companionship between equals with men still offering to care for and protect, explain how an offer of provision can read as an attempt at control, and show both sexes talking past each other in good faith.'],
            ['"Gloria Allred-itis": The Fear of the Accusation', 'Name the chilling effect on ordinary social risk', 'Trace how harassment headlines, workplace policies, and viral shaming taught men that one misread signal could cost a reputation or a career, how the compliment and the invitation became legal hazards in men\'s minds, and how the safest move became no move at all.'],
            ['The App Took the Approach', 'Show how dating apps replaced the skill they promised to assist', 'Explain how swipe platforms outsourced the introduction, concentrated most matches on a small minority of men, privatized rejection into silence, and let the muscle of walking up and saying hello atrophy across an entire generation.'],
            ['Nowhere Left to Meet', 'Document the disappearance of the places where approaches happened', 'Chart the decline of churches, dance halls, clubs, bowling leagues, and front-porch neighborhoods, the workplace ruled out as a courting ground, and the shrinking list of settings where a respectful introduction is even possible.'],
            ['Substitute Lives on a Screen', 'Confront the easy substitutes for real courtship', 'Weigh pornography, gaming, and parasocial attachment as low-risk replacements for approaching a real woman, show how each delivers reward without the possibility of rejection, and ask what happens to motivation when the substitute is always available.'],
            ['The Numbers: Sexlessness and Singleness', 'Support the whole account with the data record', 'Assemble the statistics that anchor the argument: the share of young men reporting no sex in a year, the never-married lines crossing historic highs, couples meeting online overtaking every other way of meeting, and the surveys showing how few men still approach in person.'],
            ['The Retreating Man', 'Measure the impact where it lands hardest: on men themselves', 'Document the male retreat behind the numbers: friendship circles shrinking to zero, confidence eroding from disuse, young men checking out of dating and then of ambition itself, and the resentment subcultures that recruit from that despair.'],
            ['The Price Society Pays', 'Widen the lens to the costs everyone shares', 'Assemble the broader evidence: rising loneliness in both sexes, marriage postponed or abandoned, falling birth rates, communities losing the families that once anchored them, and women who openly wish men would still approach them with confidence and respect.'],
            ['What Women Actually Want From an Approach', 'Replace guesswork with what women themselves report', 'Distinguish the welcome approach from the intrusion: reading context and body language, choosing the right setting and moment, leading with warmth instead of strategy, and taking a polite no with grace.'],
            ['Relearning the Approach', 'Give men a practical path back to social courage', 'Treat approaching as a learnable skill: small graduated risks, conversation before flirtation, manners without servility, rejection reframed as information, and daily practice that rebuilds confidence the culture no longer teaches.'],
            ['A Truce Between the Sexes', 'Close with a vision both sexes can accept', 'Argue for rebuilding mutual trust, extending good faith to those who err honestly, keeping accountability for genuine misconduct, and describing the healthier courtship culture that becomes possible when men and women stop treating each other as adversaries.'],
        ];

        return array_map(
            static fn (array $chapter, int $index): array => [
                'number' => $index + 1,
                'title' => $chapter[0],
                'purpose' => $chapter[1],
                'detail' => $chapter[2],
            ],
            $chapters,
            array_keys($chapters),
        );
    }

    /**
     * The voices exposed by the book drafting tool.
     *
     * @return array<int, array{id:string, label:string, description:string, agent_name:string, agent_mission:string}>
     */
    public function writingStyles(): array
    {
        return [
            ['id' => 'teen-friendly', 'label' => 'Teen-friendly', 'description' => 'Clear, upbeat, practical, and written for real teen life.', 'agent_name' => 'The Practical Teen Guide', 'agent_mission' => 'Clear, encouraging, realistic, and immediately usable.'],
            ['id' => 'scholastic', 'label' => 'Scholastic', 'description' => 'Clear, structured, and accessible for curious learners.', 'agent_name' => 'The Learning Editor', 'agent_mission' => 'Turns complex material into a structured lesson.'],
            ['id' => 'journalistic', 'label' => 'Journalistic', 'description' => 'Reported, evidence-led, and built around a strong opening.', 'agent_name' => "The Reporter's Desk", 'agent_mission' => 'Leads with specific situations, evidence, and stakes.'],
            ['id' => 'scientific', 'label' => 'Scientific', 'description' => 'Precise, methodical, and transparent about evidence.', 'agent_name' => 'The Evidence Reviewer', 'agent_mission' => 'Separates evidence, assumptions, limits, and conclusions.'],
            ['id' => 'technical-it', 'label' => 'Technical — IT', 'description' => 'Implementation-minded, practical, and systems-aware.', 'agent_name' => 'The Systems Architect', 'agent_mission' => 'Maps inputs, steps, failure paths, and definitions of done.'],
            ['id' => 'sarcastic', 'label' => 'Sarcastic', 'description' => 'Dry, pointed, and willing to puncture weak assumptions.', 'agent_name' => 'The Shortcut Skeptic', 'agent_mission' => 'Punctures weak assumptions and replaces them with useful action.'],
            ['id' => 'humorous', 'label' => 'Humorous', 'description' => 'Warm, playful, and memorable without losing the point.', 'agent_name' => 'The Warm Comic Editor', 'agent_mission' => 'Makes the material memorable without losing accuracy.'],
            ['id' => 'long-winded', 'label' => 'Long-winded', 'description' => 'Expansive, layered, and generous with context.', 'agent_name' => 'The Context Builder', 'agent_mission' => 'Adds context and nuance without padding or repetition.'],
            ['id' => 'bullet-points', 'label' => 'Bullet points', 'description' => 'Fast to scan, modular, and built for reference.', 'agent_name' => 'The Reference Desk', 'agent_mission' => 'Makes the material fast to scan, compare, and apply.'],
            ['id' => 'conversational', 'label' => 'Conversational', 'description' => 'Direct, generous, and like a smart guide at your side.', 'agent_name' => 'The Trusted Guide', 'agent_mission' => 'Sounds like a thoughtful expert beside the reader.'],
            ['id' => 'memoir', 'label' => 'Memoir-led', 'description' => 'Reflective, personal, and grounded in lived moments.', 'agent_name' => 'The Lived-Experience Editor', 'agent_mission' => 'Moves from a human moment to meaning and application.'],
            ['id' => 'executive', 'label' => 'Executive brief', 'description' => 'Decisive, concise, and focused on action and outcomes.', 'agent_name' => 'The Decision Brief', 'agent_mission' => 'Surfaces the point, trade-offs, risks, and next action.'],
            ['id' => 'poetic', 'label' => 'Lyrical', 'description' => 'Image-rich and atmospheric while staying useful.', 'agent_name' => 'The Image and Meaning Editor', 'agent_mission' => 'Uses precise imagery while returning to practical meaning.'],
        ];
    }

    /**
     * The shared default page treatment used by the PHP reference writer.
     *
     * @return array<string, mixed>
     */
    public function defaultPageStyle(): array
    {
        return [
            'font_family' => 'Times New Roman',
            'font_size' => 12,
            'line_height' => 1.5,
            'background' => 'paper',
            'border_style' => 'solid',
            'border_width' => 1,
            'border_color' => '#d8d0c2',
            'margin' => 'standard',
            'show_page_numbers' => true,
            'page_number_position' => 'bottom-right',
            'header' => '',
            'footer' => 'Author Garry S. Howard 2026',
        ];
    }

    /**
     * Generate a working manuscript from any editable table of contents.
     *
     * @param array<int, array<string, mixed>> $chapters
     * @param string|int $length A preset name or a page target from 1 to 1000.
     * @return array{style:string, style_label:string, style_agent:array{name:string, mission:string}, length:string, page_count:int, words_per_page:int, total_word_count:int, generated_at:string, table_of_contents:array<int, array<string, mixed>>, chapters:array<int, array<string, mixed>>}
     */
    public function generateBookFromTableOfContents(
        string $topic,
        array $chapters,
        string $style = 'conversational',
        string|int $length = 'standard',
        string $audience = '',
        string $promise = '',
        array $pageStyle = [],
    ): array {
        $topic = $this->normalizeTopic($topic);
        if ($topic === '') {
            throw new InvalidArgumentException('A topic is required to generate a book.');
        }

        $validStyles = array_column($this->writingStyles(), 'id');
        $style = in_array($style, $validStyles, true) ? $style : 'conversational';
        $presetPages = ['short' => 120, 'standard' => 240, 'expanded' => 500];
        if (is_int($length) || (is_string($length) && ctype_digit($length))) {
            $pageCount = max(1, min(1000, (int) $length));
            $length = $pageCount <= 150 ? 'short' : ($pageCount >= 500 ? 'expanded' : 'custom');
        } else {
            $length = in_array($length, array_keys($presetPages), true) ? $length : 'standard';
            $pageCount = $presetPages[$length];
        }
        $audience = $this->normalizeTopic($audience) ?: 'curious readers';
        $promise = $this->normalizeTopic($promise) ?: 'understand the topic and make a better decision';
        $styleDefinition = $this->writingStyles()[array_search($style, $validStyles, true)];
        $styleLabel = $styleDefinition['label'];

        $normalizedChapters = [];
        foreach (array_values($chapters) as $index => $chapter) {
            if (!is_array($chapter)) {
                continue;
            }
            $normalizedChapters[] = [
                'title' => trim((string) ($chapter['title'] ?? 'Chapter ' . ($index + 1))) ?: 'Chapter ' . ($index + 1),
                'purpose' => trim((string) ($chapter['purpose'] ?? 'Move the argument forward')) ?: 'Move the argument forward',
                'detail' => trim((string) ($chapter['detail'] ?? 'Use a concrete example, a clear explanation, and a small action the reader can take.')) ?: 'Use a concrete example, a clear explanation, and a small action the reader can take.',
            ];
        }
        $plans = $this->analyzeChapterPlans($normalizedChapters, $pageCount);
        $draftChapters = [];
        foreach ($normalizedChapters as $index => $chapter) {
            $plan = $plans[$index];
            $content = $this->isTeenJobsTopic($topic)
                ? $this->composeTeenJobsChapterDraft($topic, $audience, $chapter['title'], $chapter['purpose'], $chapter['detail'], $plan, $index)
                : $this->composeExpandedChapterDraft($topic, $audience, $promise, $chapter['title'], $chapter['purpose'], $chapter['detail'], $style, $plan, $index);
            $content = trim(preg_replace('/\R{3,}/u', "\n\n", $content) ?? $content);
            $draftChapters[] = [
                'number' => count($draftChapters) + 1,
                'title' => $chapter['title'],
                'purpose' => $chapter['purpose'],
                'detail' => $chapter['detail'],
                'content' => $content,
                'blocks' => $this->documentBlocks($content, $chapter['title']),
                'page_count' => $plan['page_count'],
                'word_count' => $this->wordCount($content),
                'analysis' => $plan['analysis'],
            ];
        }
        $effectivePageCount = array_sum(array_column($plans, 'page_count'));
        $totalWordCount = array_sum(array_column($draftChapters, 'word_count'));
        $tableOfContents = array_map(
            static fn (array $chapter): array => [
                'number' => $chapter['number'],
                'title' => $chapter['title'],
                'purpose' => $chapter['purpose'],
                'page_count' => $chapter['page_count'],
                'word_count' => $chapter['word_count'],
            ],
            $draftChapters,
        );
        $nextChapterPage = 3;
        foreach ($tableOfContents as $entryIndex => $entry) {
            $tableOfContents[$entryIndex]['page_number'] = $nextChapterPage;
            $nextChapterPage += max(1, (int) $entry['page_count']);
        }

        return [
            'style' => $style,
            'style_label' => $styleLabel,
            'style_agent' => [
                'name' => $styleDefinition['agent_name'],
                'mission' => $styleDefinition['agent_mission'],
            ],
            'length' => $length,
            'page_count' => $effectivePageCount,
            'words_per_page' => self::WORDS_PER_PAGE,
            'total_word_count' => $totalWordCount,
            'generated_at' => gmdate(DATE_ATOM),
            'page_style' => $this->normalizePageStyle($pageStyle),
            'table_of_contents' => $tableOfContents,
            'chapters' => $draftChapters,
            'job_catalog' => $this->isTeenJobsTopic($topic) ? $this->teenJobsCatalog() : [],
        ];
    }

    /**
     * Return the canonical teen-job records used by the PHP writer and JSON API.
     *
     * @return array<int, array<string, string>>
     */
    public function teenJobsCatalog(): array
    {
        $path = __DIR__ . '/data/teen-jobs.json';
        if (!is_file($path)) {
            throw new RuntimeException('The canonical teen-job catalog is missing.');
        }
        $json = file_get_contents($path);
        if ($json === false) {
            throw new RuntimeException('The canonical teen-job catalog could not be read.');
        }
        $catalog = json_decode($json, true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($catalog) || count($catalog) !== 120) {
            throw new RuntimeException('The canonical teen-job catalog must contain exactly 120 records.');
        }
        return array_values(array_filter(
            $catalog,
            static fn (mixed $job): bool => is_array($job) && isset($job['id'], $job['title'], $job['category']),
        ));
    }

    /**
     * Allocate the requested manuscript length from the actual TOC, giving
     * richer and more central chapters a proportionally larger development plan.
     *
     * @param array<int, array{title:string, purpose:string, detail:string}> $chapters
     * @return array<int, array{page_count:int, word_count:int, weight:float, analysis:string}>
     */
    private function analyzeChapterPlans(array $chapters, int $requestedPages): array
    {
        if ($chapters === []) {
            return [];
        }

        $totalPages = max($requestedPages, count($chapters));
        $weights = [];
        foreach ($chapters as $index => $chapter) {
            $vocabulary = array_unique(preg_split('/[^a-z0-9\'-]+/i', strtolower($chapter['title'] . ' ' . $chapter['purpose'] . ' ' . $chapter['detail']), -1, PREG_SPLIT_NO_EMPTY) ?: []);
            $detailDepth = min(5, (int) ceil(strlen($chapter['detail']) / 90));
            $centerDistance = abs($index - (count($chapters) - 1) / 2) / max(1, count($chapters));
            $centrality = 1 + (1 - $centerDistance) * 0.45;
            $weights[] = (1 + min(5, count($vocabulary) / 12) + $detailDepth * 0.45) * $centrality;
        }

        $pages = array_fill(0, count($chapters), 1);
        $remainingPages = $totalPages - count($chapters);
        $weightTotal = array_sum($weights);
        $shares = [];
        foreach ($weights as $index => $weight) {
            $share = $weightTotal > 0 ? ($weight / $weightTotal) * $remainingPages : 0;
            $shares[$index] = $share;
            $pages[$index] += (int) floor($share);
        }
        $pagesLeft = $totalPages - array_sum($pages);
        while ($pagesLeft > 0) {
            $nextIndex = 0;
            $bestFraction = -1;
            foreach ($shares as $index => $share) {
                $fraction = $share - floor($share);
                if ($fraction > $bestFraction) {
                    $bestFraction = $fraction;
                    $nextIndex = $index;
                }
            }
            $pages[$nextIndex]++;
            $shares[$nextIndex] = floor($shares[$nextIndex]);
            $pagesLeft--;
        }

        $plans = [];
        foreach ($chapters as $index => $chapter) {
            $plans[] = [
                'page_count' => $pages[$index],
                'word_count' => $pages[$index] * self::WORDS_PER_PAGE,
                'weight' => $weights[$index],
                'analysis' => 'This chapter is responsible for ' . strtolower($chapter['purpose']) . '. Its ' . $pages[$index] . '-page development follows the specific instruction: ' . $chapter['detail'],
            ];
        }
        return $plans;
    }

    /**
     * Keep this topic family grounded in the actual reader's choices instead
     * of falling through to the generic business-book outline.
     *
     * @return array<int, array{number:int, title:string, purpose:string, detail:string}>
     */
    private function teenJobsTableOfContents(): array
    {
        $chapters = [
            ['A First Job Is More Than a Paycheck', 'Explain what teens can gain from work beyond money', 'Cover confidence, communication, responsibility, references, and learning what a teen does or does not want to pursue.'],
            ['You Are Not Choosing Your Whole Career Yet', 'Put first jobs in perspective', 'Explain that a job can be a short experiment, a way to help at home, a summer plan, or a first step toward a future skill.'],
            ['What Makes a Job Worth Considering?', 'Give readers practical questions for evaluating any job', 'Ask whether the work is safe and legal, realistic to start, school-friendly, reachable, clearly paid, skill-building, and honest about costs, training, equipment, and expectations.'],
            ['How This List of 120 Jobs Was Created', 'Explain the selection method in plain language', 'Clarify that the jobs represent realistic ways to earn money, gain experience, learn useful skills, work locally or online, and explore different work—not a ranking of the best jobs.'],
            ['How to Use This Book', 'Teach readers how to move through the book and take action', 'Start with interesting jobs, check schedule and transportation, read what the work involves, review safety and training, compare costs and possible pay, investigate two or three options, and take one safe next step.'],
            ['Start With What You Like—and What You Can Handle', 'Help readers match work to interests and comfort level', 'Explore working with people, animals, food, tools, technology, numbers, ideas, or physical activity, along with energy level, noise, pace, responsibility, and comfort with strangers.'],
            ['Fit the Job Around School and Real Life', 'Help readers plan around their actual responsibilities', 'Compare after-school, weekend, summer, seasonal, part-time, one-time, and flexible work while considering homework, sports, family, sleep, transportation, and changing availability.'],
            ['Understand Pay, Costs, and the Real Value of a Job', 'Teach readers to look beyond the advertised pay rate', 'Cover tips, unpaid time, commuting, equipment, uniforms, supplies, training fees, payment schedules, and the value of learning a skill.'],
            ['Check Safety, Age Rules, and Red Flags', 'Help readers recognize safe work and avoid scams', 'Explain youth-work rules, permits, supervision, breaks, protective equipment, privacy, harassment, unsafe locations, unpaid trial work, and employers who ask for money or sensitive information.'],
            ['Compare Jobs Without Getting Overwhelmed', 'Give readers a simple way to compare opportunities', 'Use a scorecard for interest, schedule, transportation, safety, start-up cost, training, possible pay, skills learned, and the chance of finding work locally.'],
            ['Food and Restaurant Jobs', 'Introduce food-service options for teens', 'Cover cashier, host, prep cook, dishwasher, bakery helper, café worker, deli helper, and catering assistant, including beginner skills, pace, food safety, and how to ask about openings.'],
            ['Hotel, Event, Camp, and Recreation Jobs', 'Connect people skills with familiar community settings', 'Cover guest services, housekeeping support, event setup, camp work, ticketing, recreation programs, and lifeguarding where training is required.'],
            ['Store and Customer Service Jobs', 'Turn everyday communication into job-ready skills', 'Explore cashiering, stocking, sales help, bookstore work, grocery support, repair counters, and seasonal retail.'],
            ['Hands-On Jobs and Skilled Trades', 'Make practical work and trade pathways visible', 'Introduce landscaping, painting, construction support, fencing, pressure washing, moving help, and early pathways into trades.'],
            ['Animal, Farm, and Outdoor Jobs', 'Offer options for teens who prefer active outdoor work', 'Cover dog walking, pet sitting, stable work, greenhouse help, nursery work, farm work, gardening, and park or trail support.'],
            ['Making, Packing, and Behind-the-Scenes Jobs', 'Explain practical work that happens away from the public', 'Cover packaging, inventory, print-shop work, production support, quality checking, auto detailing, cleaning, and legally permitted warehouse work.'],
            ['Jobs Around Your Neighborhood', 'Turn local trust into flexible work', 'Include lawn care, leaf cleanup, snow shoveling, car washing, window cleaning, babysitting, tutoring, errands, and trash-bin services.'],
            ['Creative and Digital Jobs', 'Show how creative skills can become real experience', 'Cover photography, video editing, art commissions, simple design, website help, social media assistance, and other portfolio-building work.'],
            ['Online Jobs: What Is Real?', 'Separate real online opportunities from internet hype', 'Explain online tutoring, research help, transcription, moderated support, virtual assistant tasks, and how to recognize fake opportunities.'],
            ['Small Services You Can Run From Home', 'Help readers turn a skill or interest into a small service', 'Explore crafts, baking where permitted, reselling, study support, computer help, photography, editing, and other small services.'],
            ['Find Real Opportunities Near You', 'Give readers a repeatable way to find legitimate openings', 'Show where to look: local businesses, schools, libraries, parks, farms, community centers, job fairs, trusted adults, and reputable job sites.'],
            ['Write Your First Resume and Introduction', 'Help teens describe their real experience confidently', 'Use school projects, volunteering, informal work, responsibilities, interests, and skills without pretending to have years of experience.'],
            ['Apply, Interview, and Follow Up', 'Make the first application feel manageable', 'Include practical scripts for asking about openings, introducing yourself, answering interview questions, discussing availability, and sending a follow-up message.'],
            ['Know What to Ask Before Saying Yes', 'Give readers a final checklist before accepting work', 'Cover duties, schedule, pay, training, supervisor, transportation, breaks, equipment, start date, and what happens if school or family plans change.'],
            ['Learn From the First Job', 'Turn an early job into useful self-knowledge', 'Help readers review what they learned, what surprised them, what they enjoyed, what they would avoid next time, and which skills they want to build next.'],
            ['Your Next Step', 'Close with several realistic paths forward', 'Offer options to keep the job, try a different setting, learn a trade, take a class, build a service, update a resume, or explore a new interest.'],
            ['Appendices', 'Give readers quick tools they can use while choosing work', 'Include a Quick Job-Choice Scorecard, First-Job Questions Checklist, Safety and Scam Checklist, Job Search Tracker, and a 120 Jobs at a Glance index organized by interest, schedule, setting, and skill.'],
        ];

        return array_map(
            static fn (array $chapter, int $index): array => [
                'number' => $index + 1,
                'title' => $chapter[0],
                'purpose' => $chapter[1],
                'detail' => $chapter[2],
            ],
            $chapters,
            array_keys($chapters),
        );
    }

    /**
     * Write teen-job chapters with concrete examples and first-job language.
     *
     * @param array{page_count:int, word_count:int, weight:float, analysis:string} $plan
     */
    private function composeTeenJobsChapterDraft(
        string $topic,
        string $audience,
        string $title,
        string $purpose,
        string $detail,
        array $plan,
        int $index,
    ): string {
        $jobs = $this->teenJobsForChapter($title);
        $examples = array_map(static fn (array $job): string => (string) $job['title'], $jobs);
        $voice = 'Keep the language direct, encouraging, and realistic. Explain unfamiliar words instead of sounding like a corporate handbook.';
        $expansionFrames = [
            'Look at the choice through a real week, not an imaginary schedule.',
            'Separate what the job promises from what a normal shift actually requires.',
            'Treat the next conversation as a fact-finding step, not a commitment.',
            'Notice which detail would make this opportunity easier or harder to sustain.',
            'Write down the question you would want answered before spending time or money.',
            'Compare the appealing part with the responsibility that comes attached to it.',
            'Ask what support, training, or supervision would make the first attempt safer.',
            'Keep the decision small enough to revise when school, transportation, or family plans change.',
            'Use evidence from a real employer, customer, teacher, or trusted adult instead of guessing.',
            'End with one action that creates useful information for the next decision.',
        ];
        $sections = [
            "Start with a situation a teen might actually recognize: checking a bus route, fitting work around school, wondering whether a first job will be worth the effort, or trying to figure out what to say to an employer. This chapter is about " . strtolower($title) . ", not about pretending every reader has the same time, money, transportation, or confidence. {$voice}",
            'Jobs to explore in this part include ' . implode(', ', array_slice($examples, 0, 12)) . ', and other nearby roles that use similar skills. A job title is only the starting point. Look for the actual tasks, hours, supervision, transportation, and what you can learn. ' . $voice,
            "Before saying yes, ask practical questions: What would I do on a normal shift? What training comes first? What happens if school, weather, or transportation changes my availability? Who can I ask for help? Clear questions make a teen look prepared, not difficult. {$voice}",
            'Try matching the work to your strengths. Someone who likes talking with people may enjoy a busy customer-facing role. Someone who prefers focused tasks may like stocking, packing, cleaning, gardening, editing, or animal care. You do not need a whole career plan to choose a useful next experiment. ' . $voice,
            'Make a small plan for getting started: list three local places, write a two-sentence introduction, check the age and safety rules where you live, and ask a trusted adult or teacher to review the plan. A first step should be specific enough to complete this week. ' . $voice,
            'The point is not to collect impressive-sounding titles. It is to find honest work with clear expectations, fair treatment, and a chance to build reliability, communication, problem-solving, and follow-through. Those skills travel with you when you try the next opportunity. ' . $voice,
        ];
        $content = "Chapter " . ($index + 1) . ": {$title}\n\n{$purpose}\n\nThis chapter helps {$audience} explore {$topic} through " . strtolower($detail) . "\n\n{$voice}\n\n";
        if ($jobs !== []) {
            $content .= (str_contains(strtolower($title), 'at a glance') ? 'The complete 120-job index' : 'Job cards for ' . strtolower($title)) . "\n\n";
            foreach ($jobs as $jobIndex => $job) {
                $content .= ($jobIndex + 1) . '. ' . $job['title']
                    . "\nWhat you do: " . $job['does']
                    . "\nWho it suits: " . $job['suits']
                    . "\nWhere to find it: " . $job['find']
                    . "\nHow to start: " . $job['start']
                    . "\nSkills and training: " . $job['skills']
                    . "\nSchedule: " . $job['schedule']
                    . "\nSafety and age rules: " . $job['safety'] . "\n\n";
            }
        }
        if (count($jobs) === 120) {
            return $content . "\nChapter takeaway\n\nUse the catalog as a menu, not a demand to try everything. Choose one safe, realistic conversation and one small action while protecting your time, safety, school responsibilities, and future choices.";
        }
        $currentWords = $this->wordCount($content);
        $beat = 0;
        while ($currentWords < $plan['word_count']) {
            $example = $examples !== [] ? $examples[$beat % count($examples)] : 'a local entry-level opportunity';
            $paragraph = $sections[$beat % count($sections)];
            $frame = $expansionFrames[$beat % count($expansionFrames)];
            $jobDetail = $examples !== []
                ? "For {$example}, the catalog says: " . $jobs[$beat % count($jobs)]['does'] . " Check that description against the actual duties, schedule, supervision, and training before treating the title as a promise."
                : 'Apply that idea to a real situation involving school, transportation, safety, cost, availability, or support.';
            $addition = "\n\n{$frame}\n\n{$paragraph} {$jobDetail}";
            $content .= $addition;
            $currentWords += $this->wordCount($addition);
            $beat++;
        }

        $closing = "\n\nChapter takeaway\n\nFor " . strtolower($title) . ", start with one safe, realistic conversation and one small action. The goal is to learn more about the work while protecting your time, safety, school responsibilities, and future choices.";
        // Reserve room for the takeaway so the word-target trim never cuts it off.
        $body = $this->trimToWordTarget($content, max(1, $plan['word_count'] - $this->wordCount($closing)));
        return $body . $closing;
    }

    /** @return array<int, array<string, string>> */
    private function teenJobsForChapter(string $title): array
    {
        $normalized = strtolower($title);
        if (str_contains($normalized, 'at a glance')) {
            return $this->teenJobsCatalog();
        }
        $categoryByFriendlyTitle = [
            'food and restaurant jobs' => 'Jobs in Food',
            'hotel, event, camp, and recreation jobs' => 'Jobs in Hospitality',
            'hands-on jobs and skilled trades' => 'Jobs in Construction and Skilled Trades',
            'store and customer service jobs' => 'Jobs in Retail and Customer Service',
            'animal, farm, and outdoor jobs' => 'Jobs in Farming, Animals, and Outdoor Work',
            'making, packing, and behind-the-scenes jobs' => 'Jobs in Industry, Warehouses, and Making Things',
            'jobs around your neighborhood' => 'Door-to-Door and Neighborhood Work',
            'creative and digital jobs' => 'Remote Work',
            'online jobs: what is real?' => 'Remote Work',
            'small services you can run from home' => 'Work at Home',
        ];
        $category = $categoryByFriendlyTitle[$normalized] ?? $title;
        return array_values(array_filter(
            $this->teenJobsCatalog(),
            static fn (array $job): bool => ($job['category'] ?? '') === $category,
        ));
    }

    /**
     * Build enough distinct, TOC-specific sections to meet the chapter's
     * allocated word budget. The older short scaffold remains below as a
     * compatibility seam for callers that may still use it indirectly.
     *
     * @param array{page_count:int, word_count:int, weight:float, analysis:string} $plan
     */
    private function composeExpandedChapterDraft(
        string $topic,
        string $audience,
        string $promise,
        string $title,
        string $purpose,
        string $detail,
        string $style,
        array $plan,
        int $index,
    ): string {
        $chapterNumber = $index + 1;
        $detailClauses = preg_split('/[,.;:]+|\band\b/i', $detail, -1, PREG_SPLIT_NO_EMPTY) ?: [];
        $detailClauses = array_values(array_filter(array_map('trim', $detailClauses), static fn (string $part): bool => strlen($part) > 12));
        $focusTerms = array_values(array_unique(preg_split('/[^a-z0-9\'-]+/i', strtolower($title . ' ' . $purpose . ' ' . $detail), -1, PREG_SPLIT_NO_EMPTY) ?: []));
        $sectionNames = [
            'The question this chapter answers',
            'What the reader must notice',
            'The working model',
            'A close look at the situation',
            'Choices, trade-offs, and constraints',
            'A practical test',
            'When the idea breaks',
            'Transfer to the reader’s world',
            'Chapter synthesis',
        ];
        $actors = ['a first-time reader', 'a team lead', 'a skeptical practitioner', 'a person making the decision', 'a group reviewing the result'];
        $lenses = [
            'Start from the ordinary moment where this becomes visible.',
            'Name the assumption that makes the problem harder than it first appears.',
            'Separate the attractive explanation from the explanation that can survive a real test.',
            'Look at the decision from the perspective of the person who carries its consequences.',
            'Trace what changes when the idea meets limited time, attention, money, or authority.',
            'Put the principle beside a plausible alternative and compare the trade-offs.',
            'Ask what evidence would change the reader’s mind rather than merely confirm it.',
            'Turn the idea into a sequence someone could actually try and review.',
            'Carry the lesson forward without pretending that every context behaves the same way.',
        ];
        $styleFrames = [
            'scholastic' => 'Explain the idea in a way that rewards careful learners and makes each new term earn its place.',
            'journalistic' => 'Keep the human stakes visible, distinguish what is observed from what is inferred, and let the unanswered question pull the section forward.',
            'scientific' => 'State the working claim, identify the variables, and be explicit about what the available reasoning can and cannot establish.',
            'technical-it' => 'Translate the idea into inputs, decisions, failure paths, and an observable definition of done.',
            'sarcastic' => 'Puncture the confident shortcut, then replace it with a test that can survive contact with reality.',
            'humorous' => 'Let the situation be recognizable and lightly absurd, but make the reader’s next move unmistakably useful.',
            'long-winded' => 'Give the context, the exceptions, and the implications enough room to become clear before arriving at the practical point.',
            'bullet-points' => 'Make the reasoning modular, scannable, and easy to turn into a checklist without flattening the important nuance.',
            'conversational' => 'Sound like a thoughtful guide who is beside the reader, not above them, and keep the next step concrete.',
            'memoir' => 'Move between a lived moment, the meaning the moment revealed, and the wider pattern a reader can recognize in their own life.',
            'executive' => 'Make the decision, consequence, evidence, and recommended next move easy to find.',
            'poetic' => 'Use a precise image for the idea, then return to the practical signal the reader can notice and act on.',
        ];
        $voice = $styleFrames[$style] ?? $styleFrames['conversational'];
        $analysis = $plan['analysis'];
        $content = "Chapter {$chapterNumber}: {$title}\n\nEditorial development plan: {$analysis}\n\nThis chapter helps {$audience} understand how {$topic} connects to the larger promise to " . strtolower($promise) . ". Its specific job is to " . strtolower($purpose) . ". The chapter will not treat the title as a slogan: it will develop the instruction in the outline—{$detail}";
        $currentWords = $this->wordCount($content);
        $beat = 0;

        while ($currentWords < $plan['word_count']) {
            $section = '';
            if ($beat % 6 === 0) {
                $section = "\n\n" . $sectionNames[(int) floor($beat / 6) % count($sectionNames)] . "\n";
                $content .= $section;
                $currentWords += $this->wordCount($section);
            }
            $focus = $detailClauses !== []
                ? $detailClauses[$beat % count($detailClauses)]
                : ($focusTerms[$beat % max(1, count($focusTerms))] ?? $topic);
            $actor = $actors[$beat % count($actors)];
            $lens = $lenses[$beat % count($lenses)];
            $paragraph = match ($beat % 8) {
                0 => "In “{$title},” that means {$focus}. The chapter’s purpose—" . strtolower($purpose) . "—is clearest when {$actor} can point to a concrete situation, name the pressure involved, and see why this chapter chooses one response over another. {$voice} The useful question is not whether the idea sounds right in isolation; it is what the idea changes in the next decision.",
                1 => "{$actor} arrives here with a working theory about {$focus}. Test that theory against the chapter’s central claim: {$purpose}. A good explanation follows the sequence from context to choice to consequence, so the reader can see where the outcome was shaped and where a different move might have been possible. {$voice} Keep the example bounded enough to inspect, but rich enough to reveal the trade-off.",
                2 => "The detail in this outline is a design constraint, not filler: {$focus}. Develop it by asking what must be true before the recommendation works, what signal would show progress, and what would count as a warning. {$lens} This keeps “{$title}” attached to practice rather than drifting into general advice. {$voice} The reader should leave this passage with a clearer vocabulary and a testable next move.",
                3 => "A chapter earns its space by changing the reader’s ability to notice. Here, the change begins with {$focus}. Compare the easy interpretation with the more useful one, then show how {$actor} could respond without requiring perfect information. {$lens} Because the purpose is to " . strtolower($purpose) . ", the example must include a consequence, not just an attractive idea. {$voice}",
                4 => "Now examine the edge of the argument. If {$focus} is treated as a universal answer, where could it fail? Name the condition, the cost, and the adaptation that keeps the underlying lesson intact. {$lens} That counterexample strengthens “{$title}” because it tells {$actor} when to use the framework and when to slow down. {$voice} Precision here is more valuable than confidence.",
                5 => "Turn the discussion into a small rehearsal. Ask {$actor} to describe the current situation, choose one observable outcome, run one limited move, and review what happened. The rehearsal is grounded in {$focus} and points back to the chapter’s purpose: " . strtolower($purpose) . ". {$voice} The result is not a promise of certainty; it is a better way to learn from the next attempt.",
                6 => "The reader can now connect the local lesson to the wider book. {$title} matters because it makes {$topic} more usable for {$audience}, especially when {$focus}. Bring forward the decision rule, the evidence to collect, and the question that should remain open. {$lens} {$voice} This is how the chapter contributes to the promise rather than merely repeating it.",
                default => "Before moving on, pause over the tension between speed and care, simplicity and accuracy, or ambition and constraint. In this chapter that tension appears through {$focus}. Let {$actor} see both sides, decide what the present context requires, and record what would justify changing course. {$lens} {$voice}",
            };
            $content .= "\n\n{$paragraph}";
            $currentWords += $this->wordCount($paragraph);
            $beat++;
        }

        $closing = "\n\nChapter synthesis\n\nThe durable takeaway from “{$title}” is connected to its stated purpose: {$purpose}. A reader who can apply the detail—{$detail}—has a stronger path toward the larger promise of " . strtolower($promise) . '.';
        // Reserve room for the synthesis so the word-target trim never cuts it off.
        $body = $this->trimToWordTarget($content, max(1, $plan['word_count'] - $this->wordCount($closing)));
        return $body . $closing;
    }

    private function wordCount(string $value): int
    {
        $trimmed = trim($value);
        if ($trimmed === '') {
            return 0;
        }
        preg_match_all('/\S+/u', $trimmed, $matches);
        return count($matches[0]);
    }

    /**
     * Project generated prose into the same safe, serializable block vocabulary
     * exposed by the React editor.
     *
     * @return array<int, array<string, mixed>>
     */
    private function documentBlocks(string $content, string $title): array
    {
        $chunks = preg_split('/\R{2,}/u', trim($content), -1, PREG_SPLIT_NO_EMPTY) ?: [];
        $blocks = [];
        foreach ($chunks as $index => $chunk) {
            $chunk = trim($chunk);
            if ($chunk === '') {
                continue;
            }
            $blocks[] = [
                'id' => 'php-block-' . ($index + 1),
                'kind' => $index === 0 && preg_match('/^chapter\s+\d+/i', $chunk) === 1 ? 'heading' : 'paragraph',
                'level' => $index === 0 && preg_match('/^chapter\s+\d+/i', $chunk) === 1 ? 1 : null,
                'content' => $chunk,
            ];
        }
        if ($blocks === []) {
            $blocks[] = ['id' => 'php-block-1', 'kind' => 'paragraph', 'level' => null, 'content' => $title];
        }
        return $blocks;
    }

    /**
     * Accept page-style values from the reference form while rejecting
     * unsupported values before they reach the HTML renderer.
     *
     * @param array<string, mixed> $value
     * @return array<string, mixed>
     */
    private function normalizePageStyle(array $value): array
    {
        $defaults = $this->defaultPageStyle();
        $allowedBackgrounds = ['paper', 'linen', 'clean', 'mist'];
        $allowedBorders = ['none', 'solid', 'double', 'dashed'];
        $allowedMargins = ['compact', 'standard', 'wide'];
        $allowedPositions = ['bottom-center', 'bottom-right'];
        $font = trim((string) ($value['font_family'] ?? $defaults['font_family']));
        return [
            ...$defaults,
            'font_family' => $font !== '' ? $font : $defaults['font_family'],
            'font_size' => max(12, min(28, (int) ($value['font_size'] ?? $defaults['font_size']))),
            'line_height' => max(1.2, min(2.2, (float) ($value['line_height'] ?? $defaults['line_height']))),
            'background' => in_array($value['background'] ?? '', $allowedBackgrounds, true) ? $value['background'] : $defaults['background'],
            'border_style' => in_array($value['border_style'] ?? '', $allowedBorders, true) ? $value['border_style'] : $defaults['border_style'],
            'border_width' => max(0, min(8, (int) ($value['border_width'] ?? $defaults['border_width']))),
            'border_color' => preg_match('/^#[0-9a-f]{6}$/i', (string) ($value['border_color'] ?? '')) === 1 ? $value['border_color'] : $defaults['border_color'],
            'margin' => in_array($value['margin'] ?? '', $allowedMargins, true) ? $value['margin'] : $defaults['margin'],
            'show_page_numbers' => filter_var($value['show_page_numbers'] ?? $defaults['show_page_numbers'], FILTER_VALIDATE_BOOLEAN),
            'page_number_position' => in_array($value['page_number_position'] ?? '', $allowedPositions, true) ? $value['page_number_position'] : $defaults['page_number_position'],
            'header' => trim((string) ($value['header'] ?? '')),
            'footer' => trim((string) ($value['footer'] ?? '')),
        ];
    }

    private function trimToWordTarget(string $value, int $target): string
    {
        $value = trim($value);
        preg_match_all('/\S+/u', $value, $matches, PREG_OFFSET_CAPTURE);
        if (count($matches[0]) <= $target) {
            return $value;
        }
        // Cut after the target-th word while preserving the paragraph
        // structure between the words that remain.
        [$word, $offset] = $matches[0][$target - 1];
        return substr($value, 0, $offset + strlen($word));
    }

    private function composeChapterDraft(
        string $topic,
        string $audience,
        string $promise,
        string $title,
        string $purpose,
        string $detail,
        string $style,
        string $length,
        int $index,
    ): string {
        $chapterNumber = $index + 1;
        $core = "This chapter helps {$audience} see how {$topic} becomes useful in practice.";
        $extra = $length === 'short'
            ? ''
            : "\n\nA useful test is to ask: what would change on an ordinary Tuesday if this were true? Use the answer to choose the example, evidence, or exercise that belongs here.";
        $expanded = $length === 'expanded'
            ? "\n\nAdd a counterexample before the chapter closes. Show where the idea breaks, which assumption caused the break, and how a thoughtful reader can adapt."
            : '';
        $close = "By the end, the reader should be able to connect this idea to the larger promise: " . strtolower($promise) . '.';

        return match ($style) {
            'scholastic' => "Chapter {$chapterNumber}: {$title}\n\nLet us begin with a simple question: what does this idea ask the reader to notice? {$core} Define the important terms in plain language, then build from the familiar toward the more complex.\n\nKey lesson: {$detail} Invite the reader to pause, summarize the idea in their own words, and connect it to one real situation.{$extra}{$expanded}\n\nReview: {$close}",
            'journalistic' => "Chapter {$chapterNumber}: {$title}\n\nThe story starts with a tension that is easy to recognize but harder to explain. {$core} Follow the evidence through a person, decision, or moment that puts the stakes on the page.\n\nThe reporting question is simple: who is affected, what changed, and what did the people involved believe they were doing? {$detail} Let the facts carry the drama, and keep the unanswered question visible until the final pages.{$extra}{$expanded}\n\nThe takeaway: {$close}",
            'scientific' => "Chapter {$chapterNumber}: {$title}\n\nQuestion. How does this part of {$topic} influence the outcome for {$audience}?\n\nWorking model. {$detail} Separate observation from interpretation, name the variables that matter, and show which claims are well supported versus still provisional.{$extra}{$expanded}\n\nLimitation. No single example proves a universal rule. State what would need to be tested next.\n\nConclusion. {$close}",
            'technical-it' => "Chapter {$chapterNumber}: {$title}\n\nObjective: give {$audience} an implementation-ready understanding of this part of {$topic}.\n\nContext: {$core} Inputs include the current workflow, the people accountable for the outcome, and the constraints that cannot be ignored.\n\nRunbook: {$detail} Start with the smallest reversible change, define the success signal, document the failure path, and keep a human review point wherever the cost of a wrong decision is high.{$extra}{$expanded}\n\nDefinition of done: {$close}",
            'sarcastic' => "Chapter {$chapterNumber}: {$title}\n\nApparently, everyone already understands {$topic}. That is why the advice is usually broad, confident, and mysteriously impossible to use. {$core}\n\nHere is the less glamorous version: {$detail} The goal is not to perform expertise for a room. It is to make a decision that survives contact with reality.{$extra}{$expanded}\n\nAnd now for the part where we pretend this was obvious all along: {$close}",
            'humorous' => "Chapter {$chapterNumber}: {$title}\n\nImagine {$topic} as a group project where the instructions are missing, the deadline is yesterday, and someone keeps saying, “We should probably make a framework.” {$core}\n\nThe good news is that the situation is less doomed than it looks. {$detail} Keep the example vivid, let the reader smile at the absurdity, then hand them one move that makes the next attempt easier.{$extra}{$expanded}\n\nThe punchline with practical value: {$close}",
            'long-winded' => "Chapter {$chapterNumber}: {$title}\n\nBefore we can properly consider this chapter, it is worth acknowledging that the apparently straightforward question at its center has accumulated several layers of context, expectation, and inherited language. {$core}\n\nThat context matters because {$detail} We should resist the tempting shortcut of moving immediately to advice; the reader deserves to understand the shape of the problem, the reasons it has remained difficult, and the circumstances in which a seemingly sensible solution might fail.{$extra}{$expanded}\n\nHaving made that longer journey, we can return to the practical point: {$close}",
            'bullet-points' => "Chapter {$chapterNumber}: {$title}\n\n- Reader: {$audience}\n- Chapter job: {$purpose}\n- Core idea: {$core}\n- Explain: {$detail}\n- Show: one concrete case with context, decision, trade-off, and result\n- Practice: ask what would change on an ordinary Tuesday\n- Watch for: advice that sounds impressive but cannot be tested\n- Outcome: {$close}",
            'memoir' => "Chapter {$chapterNumber}: {$title}\n\nI first understood this question through a small moment that did not look important at the time. It showed me that {$topic} is never only a system or a category; it is also a series of choices made by real people, often with incomplete information.\n\nThat is the doorway into this chapter for {$audience}. {$detail} Stay close to the moment where the decision becomes visible, then widen the lens so the reader can recognize their own version of it.{$extra}{$expanded}\n\nWhat I carry forward is this: {$close}",
            'executive' => "Chapter {$chapterNumber}: {$title}\n\nDecision in brief: {$core}\n\nWhy it matters: {$detail}\n\nRecommended move:\n1. Define the outcome.\n2. Run the smallest credible test.\n3. Review the evidence with the people accountable for the result.\n4. Scale only what earns its next investment.{$extra}{$expanded}\n\nBottom line: {$close}",
            'poetic' => "Chapter {$chapterNumber}: {$title}\n\nEvery useful idea begins as a shape the reader can almost see. In this chapter, {$topic} moves from abstraction into the hands of {$audience}.\n\n{$detail} Let the explanation keep its edges: the friction, the pause, the small signal that tells us the system is changing. A framework is not a cage; it is a way to notice what was already there.{$extra}{$expanded}\n\nCarry this image forward: {$close}",
            default => "Chapter {$chapterNumber}: {$title}\n\nLet’s make this practical. {$core} Start with the part readers are most likely to recognize, then give them a cleaner way to name what is happening.\n\nHere is the move: {$detail} You do not need to solve the whole category in one sitting. You need a useful next step, a way to notice what happened, and a reason to try again.{$extra}{$expanded}\n\nKeep this with you: {$close}",
        };
    }

    public function optimizeMedia(string $topic, array $topicAnalysis, array $competition, array $blueprint): array
    {
        $density = $this->clamp(
            44 + ($topicAnalysis['scores']['topic_demand']['value'] * 0.19) + ($competition['scores']['media_opportunity']['value'] * 0.34),
            0,
            100,
        );

        return [
            'media_density_score' => $this->score($density),
            'recommended_mix' => [
                ['type' => 'Diagrams', 'count' => 8, 'role' => 'Make systems, sequences, and relationships graspable at a glance.'],
                ['type' => 'Annotated images', 'count' => 12, 'role' => 'Add proof, texture, and visual memory to case studies.'],
                ['type' => 'Interactive exercises', 'count' => 6, 'role' => 'Turn passive reading into a moment of application.'],
                ['type' => 'Audio commentary', 'count' => 4, 'role' => 'Add author context, nuance, and an alternate learning mode.'],
                ['type' => 'Short video clips', 'count' => 3, 'role' => 'Demonstrate process or bring a practitioner voice into the book.'],
            ],
            'placement_map' => [
                ['chapter' => 'Chapter 1', 'media' => 'One-page topic map', 'reason' => 'Orient the reader before introducing terminology.'],
                ['chapter' => 'Chapter 3', 'media' => 'Interactive system diagram', 'reason' => 'Let readers explore the moving parts in their own order.'],
                ['chapter' => 'Chapter 4', 'media' => 'Annotated case study gallery', 'reason' => 'Make evidence and decisions visible together.'],
                ['chapter' => 'Chapter 5', 'media' => 'Practice worksheet + audio walkthrough', 'reason' => 'Support action for both visual and listening learners.'],
            ],
            'interactive_diagram_plan' => 'Build one explorable diagram around the core process, with progressive disclosure for advanced readers.',
            'vr_ar_enhancement_plan' => 'Reserve VR/AR for optional spatial or historical topics; do not add it unless it clarifies a concept better than a diagram.',
            'audiobook_immersion_plan' => 'Add short author notes between sections, with distinct sonic cues for case studies and exercises.',
            'learning_modes' => ['Read', 'Listen', 'Explore', 'Practice'],
        ];
    }

    public function calculateProbability(
        array $topicAnalysis,
        array $competition,
        array $blueprint,
        array $media,
        array $options = [],
    ): array {
        $td = $topicAnalysis['scores']['topic_demand']['value'];
        $cg = $competition['scores']['competitive_gap']['value'];
        $es = $this->editorialStrength($blueprint);
        $ms = $media['media_density_score']['value'];
        $mp = $this->marketPositioning($topicAnalysis, $competition, $options);
        $probability = $this->clamp(($td + $cg + $es + $ms + $mp) / 5, 0, 100);

        return [
            'formula' => 'BSP = (TD + CG + ES + MS + MP) / 5',
            'score' => $this->score($probability),
            'components' => [
                ['key' => 'TD', 'label' => 'Topic demand', 'score' => $this->score($td), 'note' => 'Search intent, social energy, and audience pull.'],
                ['key' => 'CG', 'label' => 'Competitive gap', 'score' => $this->score($cg), 'note' => 'Room to be more useful, distinct, or memorable.'],
                ['key' => 'ES', 'label' => 'Editorial strength', 'score' => $this->score($es), 'note' => 'Clarity of promise, structure, proof, and practice.'],
                ['key' => 'MS', 'label' => 'Media strength', 'score' => $this->score($ms), 'note' => 'How much rich media improves understanding and recall.'],
                ['key' => 'MP', 'label' => 'Market positioning', 'score' => $this->score($mp), 'note' => 'Specificity of reader, angle, and promise.'],
            ],
            'outcomes' => [
                ['label' => 'Outperform category rivals', 'score' => $this->score($probability)],
                ['label' => 'Reach category top 10', 'score' => $this->score($this->clamp($probability - 9, 0, 100))],
                ['label' => 'Build viral traction', 'score' => $this->score($this->clamp(($probability * 0.78) + ($ms * 0.2), 0, 100))],
                ['label' => 'Create long-tail sales', 'score' => $this->score($this->clamp(($probability * 0.86) + ($topicAnalysis['scores']['topic_longevity']['value'] * 0.16), 0, 100))],
            ],
            'sales_curve' => [
                ['label' => 'Launch', 'value' => $this->clamp($probability * 0.83, 0, 100)],
                ['label' => 'Month 2', 'value' => $this->clamp($probability * 0.94, 0, 100)],
                ['label' => 'Month 6', 'value' => $this->clamp($probability * 0.76, 0, 100)],
                ['label' => 'Year 1', 'value' => $this->clamp($probability * 0.69, 0, 100)],
            ],
            'roi_timeline' => [
                'first_signal' => '4–8 weeks after launch',
                'break_even_window' => $probability >= 70 ? '3–6 months' : '6–12 months',
                'long_tail_window' => $topicAnalysis['scores']['topic_longevity']['value'] >= 68 ? '12–36 months' : '6–18 months',
            ],
        ];
    }

    private function signals(string $topic): array
    {
        $words = $this->tokens($topic);
        $length = count($words);
        $joined = implode(' ', $words);
        $trendWords = ['ai', 'viral', 'creator', 'climate', 'crypto', 'remote', 'wellness', 'future', 'hacking', 'ethics'];
        $evergreenWords = ['history', 'psychology', 'leadership', 'writing', 'finance', 'science', 'craft', 'design', 'learning', 'strategy'];
        $social = $this->keywordScore($joined, $trendWords, 36, 86);
        $evergreen = $this->keywordScore($joined, $evergreenWords, 48, 92);

        return [
            'specificity' => $this->clamp(0.42 + min($length, 6) * 0.07, 0, 1),
            'trend' => $this->clamp(42 + $social + (($length <= 4) ? 9 : 0), 0, 100),
            'evergreen' => $this->clamp($evergreen, 0, 100),
            'social' => $this->clamp(40 + $social, 0, 100),
            'academic' => $this->clamp(48 + ($evergreen * 0.28) + ($length > 2 ? 8 : 0), 0, 100),
        ];
    }

    private function audienceProfile(string $topic, array $signals): array
    {
        $label = $signals['trend'] >= 72 ? 'Curious early adopters' : 'Committed lifelong learners';

        return [
            'primary' => $label,
            'secondary' => 'Practitioners who need a clear way to explain the topic to others',
            'mindset' => 'They are informed enough to reject fluff, but busy enough to value a strong map.',
            'job_to_be_done' => 'Understand the topic, make a better decision, and have language they can share.',
            'friction' => 'Existing books either flatten the nuance or bury the useful part under exposition.',
            'topic_context' => $this->titleCase($topic),
        ];
    }

    private function angleFor(string $topic, array $signals, string $mode): array
    {
        $name = $this->titleCase($topic);
        $angles = [
            'practical' => [
                'title' => 'The practical field guide',
                'description' => 'Make ' . $name . ' usable through a repeatable framework, examples, and small experiments.',
                'fit' => $this->score($this->clamp(65 + ($signals['specificity'] * 24), 0, 100)),
            ],
            'contrarian' => [
                'title' => 'The myth-busting perspective',
                'description' => 'Challenge the category’s default assumptions and replace them with evidence readers can test.',
                'fit' => $this->score($this->clamp(53 + ($signals['trend'] * 0.28), 0, 100)),
            ],
            'human' => [
                'title' => 'The human stories behind the system',
                'description' => 'Use vivid people and decisions to make the stakes of ' . $name . ' impossible to ignore.',
                'fit' => $this->score($this->clamp(59 + ($signals['social'] * 0.23), 0, 100)),
            ],
        ];

        return $angles[$mode];
    }

    private function kitSummary(
        string $topic,
        array $topicAnalysis,
        array $competition,
        array $blueprint,
        array $media,
        array $probability,
    ): array {
        return [
            'title' => $blueprint['positioning']['working_title'],
            'subtitle' => 'A strategy kit for ' . $this->titleCase($topic),
            'headline_score' => $probability['score'],
            'deliverables' => [
                ['label' => 'Topic demand report', 'status' => 'Ready'],
                ['label' => 'Competitive gap map', 'status' => $competition['rival_count'] . ' rivals mapped'],
                ['label' => 'Chapter blueprint', 'status' => count($blueprint['chapters']) . ' chapters'],
                ['label' => 'Rich media map', 'status' => count($media['placement_map']) . ' placements'],
                ['label' => 'Probability model', 'status' => '5-factor model'],
            ],
            'next_move' => 'Pressure-test the recommended angle with three real reader conversations before drafting.',
            'method' => 'Five weighted directional scores: topic demand, competitive gap, editorial strength, media strength, and market positioning.',
        ];
    }

    private function editorialStrength(array $blueprint): float
    {
        return $this->clamp(62 + (count($blueprint['chapters']) * 3) + (count($blueprint['citation_strategy']) * 2), 0, 100);
    }

    private function marketPositioning(array $topicAnalysis, array $competition, array $options): float
    {
        $bonus = (isset($options['reader']) && trim((string) $options['reader']) !== '') ? 8 : 0;
        return $this->clamp(
            48 + ($topicAnalysis['scores']['topic_demand']['value'] * 0.22)
                + ($competition['scores']['competitive_gap']['value'] * 0.18)
                + $bonus,
            0,
            100,
        );
    }

    private function audienceEstimate(float $demand, array $audience): array
    {
        $low = (int) round(18000 + ($demand * 820));
        $high = (int) round($low * 3.2);

        return [
            'range' => number_format($low) . '–' . number_format($high) . ' engaged readers',
            'confidence' => $this->score($this->clamp(51 + ($demand * 0.35), 0, 100)),
            'basis' => 'Directional estimate based on topic specificity, intent, and audience fit.',
            'primary_persona' => $audience['primary'],
        ];
    }

    private function score(float $value): array
    {
        $rounded = (int) round($this->clamp($value, 0, 100));
        return ['value' => $rounded, 'label' => $rounded >= 78 ? 'Strong' : ($rounded >= 58 ? 'Promising' : 'Needs work')];
    }

    private function keywordScore(string $haystack, array $keywords, float $base, float $cap): float
    {
        $hits = 0;
        foreach ($keywords as $keyword) {
            if (str_contains($haystack, $keyword)) {
                $hits++;
            }
        }
        return $this->clamp($base + ($hits * 8), 0, $cap);
    }

    private function tokens(string $topic): array
    {
        $words = preg_split('/[^a-z0-9]+/i', strtolower($topic)) ?: [];
        return array_values(array_filter($words, static fn (string $word): bool => $word !== '' && !in_array($word, self::STOP_WORDS, true)));
    }

    private function isTeenJobsTopic(string $topic): bool
    {
        $normalized = strtolower($topic);
        return preg_match('/teen|teenager|youth|student|high school|young people/', $normalized) === 1
            && preg_match('/job|work|career|employment|earning|money/', $normalized) === 1;
    }

    private function normalizeTopic(string $topic): string
    {
        return trim(preg_replace('/\s+/', ' ', strip_tags($topic)) ?? '');
    }

    private function titleCase(string $value): string
    {
        return ucwords(strtolower($value));
    }

    private function clamp(float $value, float $min, float $max): float
    {
        return max($min, min($max, $value));
    }
}