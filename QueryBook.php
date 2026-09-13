<?php

declare(strict_types=1);

/**
 * QueryBook — the reader-side intelligence layer of the studio.
 *
 * Implements the original QueryBook concept: every answer is linked to a
 * target book, and readers can get those answers in many forms:
 *
 *  - ask()                  — Q&A, conversational, and research answer modes,
 *                             every answer citing the chapters it came from
 *  - domain tailoring       — answers customized to a specific industry or
 *                             domain (education, healthcare, legal, finance,
 *                             technology, …) via the `domain` option
 *  - summarize()            — book-level and chapter-level summaries
 *  - synopsis()             — the narrative walk through the book's arc
 *  - abstractText()         — a compact single-paragraph abstract
 *  - analyze()              — structural analysis of the book or one chapter
 *  - compareChapters()      — chapter-vs-chapter comparison inside the book
 *  - documentReport()       — summary/abstract/key terms for a pasted document
 *  - compareWithDocument()  — book-vs-document coverage comparison
 *
 * Everything is deterministic and computed locally from the generated book —
 * no database, no API keys. Same book + same question = same answer.
 */
final class QueryBook
{
    /** Answer modes: how the answer is shaped. */
    public const MODES = [
        'qa' => 'Q&A — a direct answer with its sources',
        'conversational' => 'Conversational — a dialogue answer that invites follow-ups',
        'research' => 'Research — an evidence-forward briefing, chapter by chapter',
        'executive' => 'Executive brief — bottom line first, decision-ready',
        'tutorial' => 'Tutorial — the answer as numbered steps in book order',
        'study' => 'Study — the answer plus self-check questions',
        'quotes' => 'Quotes — the book answers in its own words',
        'expository' => 'Expository — a plain, declarative explanation',
        'argumentative' => 'Argumentative — claim, evidence, and the counterweight',
        'descriptive' => 'Descriptive — the picture the book paints',
    ];

    /**
     * Canonical NarrativeStyle coverage, per the QueryBook Bible (Canonical
     * Core Technology Specification): the REGENERATE AS clause's style enum
     * (§18.2.5) and its style-enforcement rules (§12.4.3). Every canonical
     * style maps to a mode here; local modes beyond these are a superset.
     * DOMAINS play the Bible's Audience Model role (vocabulary, domain
     * expertise, detail level) and the `max_words` option is the local
     * MAX_TOKENS analog. The Bible itself is confidential and lives outside
     * this repository.
     */
    public const CANONICAL_STYLES = [
        'EXPOSITORY' => 'expository',
        'ARGUMENTATIVE' => 'argumentative',
        'DESCRIPTIVE' => 'descriptive',
        'ANALYTICAL' => 'research',
        'INSTRUCTIONAL' => 'tutorial',
        'CONVERSATIONAL' => 'conversational',
        'EXECUTIVE_SUMMARY' => 'executive',
    ];

    /**
     * Every form of output a user can request. request() dispatches on these
     * keys, so the whole catalog is drivable from one entry point.
     */
    public const FORMS = [
        'answer' => 'Answer — a question, in any mode and domain',
        'summary' => 'Summary — the book, or one chapter',
        'synopsis' => 'Synopsis — the narrative arc',
        'abstract' => 'Abstract — one compact paragraph',
        'analysis' => 'Analysis — structure and emphasis',
        'outline' => 'Outline — every chapter and its job',
        'glossary' => 'Glossary — key terms, defined in the book\'s own words',
        'faq' => 'FAQ — the questions the book answers, chapter by chapter',
        'study-guide' => 'Study guide — summaries, terms, discussion questions',
        'quotes' => 'Key quotes — the most quotable line of every chapter',
        'reading-plan' => 'Reading plan — a session-by-session schedule',
        'compare-chapters' => 'Comparison — chapter vs. chapter',
        'compare-document' => 'Comparison — the book vs. an outside document',
        'document-report' => 'Document report — summary and abstract of pasted text',
        'related-questions' => 'Related questions — what this book answers well',
    ];

    /**
     * Industry / domain profiles used to tailor answers.
     * lens: the phrase used to frame the answer; audience: who the tailored
     * application sentence speaks to; note: the domain-specific caution.
     */
    public const DOMAINS = [
        'general' => [
            'label' => 'General',
            'lens' => 'a general reader\'s',
            'audience' => 'most readers',
            'note' => '',
        ],
        'education' => [
            'label' => 'Education',
            'lens' => 'an educator\'s',
            'audience' => 'teachers, trainers, and curriculum designers',
            'note' => 'Adapt the material to your learners\' level before putting it in front of a class.',
        ],
        'healthcare' => [
            'label' => 'Healthcare',
            'lens' => 'a healthcare professional\'s',
            'audience' => 'clinicians, administrators, and care teams',
            'note' => 'This is publishing guidance drawn from the book, not clinical advice.',
        ],
        'legal' => [
            'label' => 'Legal',
            'lens' => 'a legal practitioner\'s',
            'audience' => 'attorneys, compliance officers, and paralegals',
            'note' => 'This is a reading of the book, not legal advice; rules vary by jurisdiction.',
        ],
        'finance' => [
            'label' => 'Finance',
            'lens' => 'a finance professional\'s',
            'audience' => 'analysts, advisors, and business owners',
            'note' => 'This is a reading of the book, not investment advice.',
        ],
        'technology' => [
            'label' => 'Technology',
            'lens' => 'a technologist\'s',
            'audience' => 'engineers, product managers, and IT leaders',
            'note' => 'Check the book\'s examples against your own stack before adopting them.',
        ],
        'small-business' => [
            'label' => 'Small business',
            'lens' => 'a small-business owner\'s',
            'audience' => 'founders, operators, and side-hustlers',
            'note' => 'Scale the book\'s recommendations to your headcount and cash position.',
        ],
    ];

    private const STOPWORDS = [
        'a', 'about', 'after', 'all', 'an', 'and', 'any', 'are', 'as', 'at', 'be', 'been', 'before',
        'but', 'by', 'can', 'chapter', 'could', 'do', 'does', 'for', 'from', 'get', 'had', 'has',
        'have', 'how', 'i', 'if', 'in', 'into', 'is', 'it', 'its', 'me', 'more', 'most', 'my', 'no',
        'not', 'of', 'on', 'one', 'or', 'our', 'out', 'over', 'she', 'should', 'so', 'some', 'tell',
        'than', 'that', 'the', 'their', 'them', 'then', 'there', 'these', 'they', 'this', 'to',
        'up', 'us', 'was', 'we', 'were', 'what', 'when', 'where', 'which', 'who', 'why', 'will',
        'with', 'would', 'you', 'your',
    ];

    /** @var array<int, array<string, mixed>> */
    private array $chapters;

    private string $title;

    private string $topic;

    /**
     * @param array<string, mixed> $book     A book from generateBookFromTableOfContents() / writeBook()['book'].
     * @param array<string, mixed> $metadata Optional: title, subtitle, topic (used to name the target book).
     */
    public function __construct(array $book, array $metadata = [])
    {
        $this->chapters = array_values((array) ($book['chapters'] ?? []));
        if ($this->chapters === []) {
            throw new InvalidArgumentException('QueryBook needs a generated book with at least one chapter.');
        }
        $title = trim((string) ($metadata['title'] ?? ''));
        $subtitle = trim((string) ($metadata['subtitle'] ?? ''));
        $this->title = $title !== '' ? ($subtitle !== '' ? $title . ': ' . $subtitle : $title) : 'this book';
        $this->topic = trim((string) ($metadata['topic'] ?? '')) ?: $this->title;
    }

    /** @return array<string, string> */
    public function modes(): array
    {
        return self::MODES;
    }

    /** @return array<string, array<string, string>> */
    public function domains(): array
    {
        return self::DOMAINS;
    }

    /**
     * Answer a question about the target book.
     *
     * @param array<string, mixed> $options Supports:
     *   mode    — qa | conversational | research (default qa)
     *   domain  — a key of DOMAINS (default general)
     *   chapter — restrict the answer to one chapter number
     * @return array<string, mixed>
     */
    public function ask(string $question, array $options = []): array
    {
        $question = trim($question);
        $mode = isset(self::MODES[$options['mode'] ?? '']) ? (string) $options['mode'] : 'qa';
        $domainKey = isset(self::DOMAINS[$options['domain'] ?? '']) ? (string) $options['domain'] : 'general';
        $domain = self::DOMAINS[$domainKey];
        $chapterFilter = isset($options['chapter']) && (int) $options['chapter'] > 0 ? (int) $options['chapter'] : null;

        $terms = $this->tokenize($question);
        $pool = $chapterFilter === null
            ? $this->chapters
            : array_values(array_filter($this->chapters, static fn (array $c): bool => (int) $c['number'] === $chapterFilter));
        if ($pool === []) {
            $pool = $this->chapters;
            $chapterFilter = null;
        }

        $ranked = [];
        foreach ($pool as $chapter) {
            $score = $this->scoreChapter($chapter, $terms);
            if ($score > 0) {
                $ranked[] = ['chapter' => $chapter, 'score' => $score];
            }
        }
        usort($ranked, static fn (array $a, array $b): int => $b['score'] <=> $a['score'] ?: (int) $a['chapter']['number'] <=> (int) $b['chapter']['number']);
        $ranked = array_slice($ranked, 0, 3);

        if ($question === '' || $terms === [] || $ranked === []) {
            return [
                'question' => $question,
                'mode' => $mode,
                'mode_label' => self::MODES[$mode],
                'domain' => $domainKey,
                'domain_label' => $domain['label'],
                'scope' => $chapterFilter === null ? 'book' : 'chapter ' . $chapterFilter,
                'confidence' => 'low',
                'answer' => [
                    ucfirst($this->title) . ' does not take that question up directly. It stays close to ' . strtolower($this->topic) . ', so the closest help it can offer is through one of its own chapters.',
                    'Try one of the related questions below — each is grounded in a chapter that can actually answer it.',
                ],
                'sources' => [],
                'follow_ups' => [],
                'related_questions' => $this->relatedQuestions(3),
            ];
        }

        $best = $ranked[0]['chapter'];
        $evidence = $this->relevantSentences((string) $best['content'], $terms, 3);
        if ($evidence === []) {
            $evidence = [$this->purposeSentence($best)];
        }

        $paragraphs = [];
        if ($mode === 'conversational') {
            $paragraphs[] = 'That question lands squarely in chapter ' . (int) $best['number'] . ', "' . $best['title'] . '". Here is how the book talks about it: ' . implode(' ', $evidence);
            $paragraphs[] = $this->purposeSentence($best) . ' If you read one chapter for this, read that one.';
        } elseif ($mode === 'research') {
            foreach ($ranked as $entry) {
                $chapter = $entry['chapter'];
                $lines = $this->relevantSentences((string) $chapter['content'], $terms, 2);
                if ($lines === []) {
                    $lines = [$this->purposeSentence($chapter)];
                }
                $paragraphs[] = 'Chapter ' . (int) $chapter['number'] . ', "' . $chapter['title'] . '": ' . implode(' ', $lines);
            }
        } elseif ($mode === 'executive') {
            $paragraphs[] = 'Bottom line: ' . $evidence[0];
            if (isset($evidence[1])) {
                $paragraphs[] = 'Why it matters: ' . $evidence[1];
            }
            $paragraphs[] = 'Where it lives: chapter ' . (int) $best['number'] . ', "' . $best['title'] . '". ' . $this->purposeSentence($best);
        } elseif ($mode === 'tutorial') {
            $ordered = $ranked;
            usort($ordered, static fn (array $a, array $b): int => (int) $a['chapter']['number'] <=> (int) $b['chapter']['number']);
            foreach ($ordered as $index => $entry) {
                $chapter = $entry['chapter'];
                $lines = $this->relevantSentences((string) $chapter['content'], $terms, 1);
                $paragraphs[] = 'Step ' . ($index + 1) . ' — chapter ' . (int) $chapter['number'] . ', "' . $chapter['title'] . '": ' . ($lines[0] ?? $this->purposeSentence($chapter));
            }
            $paragraphs[] = 'Work the steps in book order; each of those chapters closes with its own takeaway to check yourself against.';
        } elseif ($mode === 'quotes') {
            foreach ($ranked as $entry) {
                $chapter = $entry['chapter'];
                $lines = $this->relevantSentences((string) $chapter['content'], $terms, 1);
                $paragraphs[] = '“' . ($lines[0] ?? $this->purposeSentence($chapter)) . '” — chapter ' . (int) $chapter['number'] . ', "' . $chapter['title'] . '"';
            }
        } elseif ($mode === 'study') {
            $paragraphs[] = implode(' ', $evidence);
            $paragraphs[] = 'Source: chapter ' . (int) $best['number'] . ', "' . $best['title'] . '". ' . $this->purposeSentence($best) . ' Answer the self-check questions below before moving on.';
        } elseif ($mode === 'expository') {
            $paragraphs[] = $evidence[0] . (isset($evidence[1]) ? ' Furthermore, the same chapter carries it forward: ' . $evidence[1] : '');
            $paragraphs[] = 'That is the plain account, as chapter ' . (int) $best['number'] . ', "' . $best['title'] . '", lays it out. ' . $this->purposeSentence($best);
        } elseif ($mode === 'argumentative') {
            $paragraphs[] = 'The claim: ' . $evidence[0];
            $paragraphs[] = 'The evidence: ' . ($evidence[1] ?? $this->purposeSentence($best)) . ' (Chapter ' . (int) $best['number'] . ', "' . $best['title'] . '".)';
            $paragraphs[] = isset($ranked[1])
                ? 'The counterweight: chapter ' . (int) $ranked[1]['chapter']['number'] . ', "' . $ranked[1]['chapter']['title'] . '", pushes on this from another side — read it before settling the question.'
                : 'The book stages no counterargument to this; weigh it against your own experience before settling the question.';
        } elseif ($mode === 'descriptive') {
            $paragraphs[] = 'Here is the picture chapter ' . (int) $best['number'] . ', "' . $best['title'] . '", paints: ' . implode(' ', $evidence);
            $paragraphs[] = ucfirst($this->clause((string) $best['purpose'])) . ' is what the scene is doing; the details are the argument.';
        } else { // qa
            $paragraphs[] = implode(' ', $evidence);
            $paragraphs[] = 'That answer comes from chapter ' . (int) $best['number'] . ', "' . $best['title'] . '". ' . $this->purposeSentence($best);
        }

        // Domain tailoring: frame the answer through the industry lens and
        // add the tailored application sentence + the domain's caution.
        // Quotes stay verbatim, so only the application sentence is added there.
        if ($domainKey !== 'general') {
            if ($mode !== 'quotes') {
                $paragraphs[0] = 'Through ' . $domain['lens'] . ' lens: ' . $paragraphs[0];
            }
            $applied = 'For ' . $domain['audience'] . ', the working takeaway is to treat "' . $best['title'] . '" as the operating chapter and apply its steps inside your own ' . strtolower($domain['label']) . ' context.';
            if ($domain['note'] !== '') {
                $applied .= ' ' . $domain['note'];
            }
            $paragraphs[] = $applied;
        }

        $followUps = [];
        if ($mode === 'conversational') {
            foreach (array_slice($ranked, 1) as $entry) {
                $followUps[] = 'Want to go deeper — how does chapter ' . (int) $entry['chapter']['number'] . ', "' . $entry['chapter']['title'] . '", extend this?';
            }
            if ($followUps === []) {
                $followUps[] = 'Want the one-paragraph abstract of ' . $this->title . ' next?';
            }
        } elseif ($mode === 'study') {
            $followUps[] = 'Self-check: in your own words, what does chapter ' . (int) $best['number'] . ', "' . $best['title'] . '", say about this?';
            $followUps[] = 'Self-check: which part of that answer could you apply this week, and what would you expect to change?';
        }

        // Local analog of the canonical MAX_TOKENS constraint: cap the answer
        // at a word budget, cutting cleanly at paragraph or word boundaries.
        $maxWords = (int) ($options['max_words'] ?? 0);
        if ($maxWords > 0) {
            $kept = [];
            $budget = $maxWords;
            foreach ($paragraphs as $paragraph) {
                $words = preg_split('/\s+/u', trim($paragraph)) ?: [];
                if (count($words) <= $budget) {
                    $kept[] = $paragraph;
                    $budget -= count($words);
                    continue;
                }
                if ($budget > 0) {
                    $kept[] = implode(' ', array_slice($words, 0, $budget)) . '…';
                }
                break;
            }
            $paragraphs = $kept;
        }

        $maxScore = max(1, $ranked[0]['score']);
        return [
            'question' => $question,
            'mode' => $mode,
            'mode_label' => self::MODES[$mode],
            'domain' => $domainKey,
            'domain_label' => $domain['label'],
            'scope' => $chapterFilter === null ? 'book' : 'chapter ' . $chapterFilter,
            'confidence' => $maxScore >= 8 ? 'high' : ($maxScore >= 4 ? 'medium' : 'low'),
            'answer' => $paragraphs,
            'sources' => array_map(static fn (array $entry): array => [
                'chapter' => (int) $entry['chapter']['number'],
                'title' => (string) $entry['chapter']['title'],
                'relevance' => (int) round($entry['score'] * 100 / $maxScore),
            ], $ranked),
            'follow_ups' => $followUps,
            'related_questions' => $this->relatedQuestions(3),
        ];
    }

    /**
     * Book-level or chapter-level summary.
     *
     * @param string $length brief (one line), standard, or detailed.
     * @return array<string, mixed>
     */
    public function summarize(?int $chapterNumber = null, string $length = 'standard'): array
    {
        $length = in_array($length, ['brief', 'standard', 'detailed'], true) ? $length : 'standard';
        if ($chapterNumber !== null) {
            $chapter = $this->findChapter($chapterNumber);
            $opening = $this->firstSentences((string) $chapter['content'], $length === 'detailed' ? 3 : 2);
            $lines = $length === 'brief'
                ? [$this->purposeSentence($chapter)]
                : array_values(array_filter([
                    $this->purposeSentence($chapter),
                    $opening === [] ? '' : 'It opens: ' . implode(' ', $opening),
                    'It runs ' . (int) $chapter['word_count'] . ' words across about ' . (int) $chapter['page_count'] . ' pages.',
                ], static fn (string $line): bool => $line !== ''));
            return [
                'scope' => 'chapter',
                'length' => $length,
                'chapter' => (int) $chapter['number'],
                'title' => (string) $chapter['title'],
                'summary' => $lines,
                'key_terms' => $this->keyTerms((string) $chapter['content'], $length === 'brief' ? 4 : 6),
            ];
        }

        $lines = [];
        if ($length !== 'brief') {
            foreach ($this->chapters as $chapter) {
                $line = 'Chapter ' . (int) $chapter['number'] . ' — ' . $chapter['title'] . ': ' . $this->clause((string) $chapter['purpose']) . '.';
                if ($length === 'detailed') {
                    $opening = $this->firstSentences((string) $chapter['content'], 1);
                    if ($opening !== []) {
                        $line .= ' It opens: ' . $opening[0];
                    }
                }
                $lines[] = $line;
            }
        }
        return [
            'scope' => 'book',
            'length' => $length,
            'title' => $this->title,
            'summary' => [
                ucfirst($this->title) . ' covers ' . strtolower($this->topic) . ' in ' . count($this->chapters) . ' chapters, about ' . $this->totalWords() . ' words in all.',
                'It moves from "' . $this->chapters[0]['title'] . '" to "' . $this->chapters[count($this->chapters) - 1]['title'] . '", and every chapter closes with its takeaway.',
            ],
            'chapters' => $lines,
            'key_terms' => $this->keyTerms($this->allContent(), 8),
        ];
    }

    /**
     * The narrative synopsis: a walk through the book's arc.
     *
     * @return array<int, string> Paragraphs.
     */
    public function synopsis(): array
    {
        $count = count($this->chapters);
        $first = $this->chapters[0];
        $last = $this->chapters[$count - 1];
        $middle = array_slice($this->chapters, 1, max(0, $count - 2));

        $paragraphs = [
            ucfirst($this->title) . ' opens with "' . $first['title'] . '", where the goal is to ' . $this->clause((string) $first['purpose']) . '.',
        ];
        if ($middle !== []) {
            $steps = array_map(
                fn (array $chapter): string => '"' . $chapter['title'] . '" (' . $this->clause((string) $chapter['purpose']) . ')',
                $middle,
            );
            $paragraphs[] = 'From there it builds through ' . $this->joinList($steps) . '.';
        }
        if ($count > 1) {
            $paragraphs[] = 'It closes with "' . $last['title'] . '", which exists to ' . $this->clause((string) $last['purpose']) . ' — the place the whole argument has been heading.';
        }
        return $paragraphs;
    }

    /** A compact single-paragraph abstract of the target book. */
    public function abstractText(int $maxWords = 200): string
    {
        $count = count($this->chapters);
        $purposes = array_map(
            fn (array $chapter): string => $this->clause((string) $chapter['purpose']),
            array_slice($this->chapters, 0, 4),
        );
        $abstract = ucfirst($this->title) . ' is ' . (in_array($count, [8, 11, 18], true) || ($count >= 80 && $count <= 89) ? 'an ' : 'a ') . $count . '-chapter treatment of ' . strtolower($this->topic) . '. '
            . 'It sets out to ' . $this->joinList($purposes) . ($count > 4 ? ', among other things' : '') . '. '
            . 'The chapters run about ' . $this->totalWords() . ' words in total, each ending on its own takeaway, '
            . 'so a reader can move from first contact with the subject to a decision they can defend.';
        $words = preg_split('/\s+/u', trim($abstract)) ?: [];
        if (count($words) > $maxWords) {
            $abstract = implode(' ', array_slice($words, 0, $maxWords)) . '…';
        }
        return $abstract;
    }

    /**
     * Structural analysis of the book (or one chapter).
     *
     * @return array<string, mixed>
     */
    public function analyze(?int $chapterNumber = null): array
    {
        if ($chapterNumber !== null) {
            $chapter = $this->findChapter($chapterNumber);
            $content = (string) $chapter['content'];
            $sentences = $this->sentences($content);
            return [
                'scope' => 'chapter',
                'chapter' => (int) $chapter['number'],
                'title' => (string) $chapter['title'],
                'word_count' => (int) $chapter['word_count'],
                'page_count' => (int) $chapter['page_count'],
                'sentence_count' => count($sentences),
                'average_sentence_words' => $sentences === [] ? 0 : (int) round((int) $chapter['word_count'] / count($sentences)),
                'has_takeaway' => str_contains($content, 'The takeaway'),
                'key_terms' => $this->keyTerms($content, 8),
                'reading' => $this->purposeSentence($chapter),
            ];
        }

        $wordCounts = array_map(static fn (array $c): int => (int) $c['word_count'], $this->chapters);
        $longest = $this->chapters[(int) array_search(max($wordCounts), $wordCounts, true)];
        $shortest = $this->chapters[(int) array_search(min($wordCounts), $wordCounts, true)];
        $withTakeaway = count(array_filter($this->chapters, static fn (array $c): bool => str_contains((string) $c['content'], 'The takeaway')));
        return [
            'scope' => 'book',
            'title' => $this->title,
            'chapter_count' => count($this->chapters),
            'total_words' => $this->totalWords(),
            'average_chapter_words' => (int) round($this->totalWords() / count($this->chapters)),
            'longest_chapter' => ['chapter' => (int) $longest['number'], 'title' => (string) $longest['title'], 'words' => (int) $longest['word_count']],
            'shortest_chapter' => ['chapter' => (int) $shortest['number'], 'title' => (string) $shortest['title'], 'words' => (int) $shortest['word_count']],
            'takeaway_coverage' => $withTakeaway . ' of ' . count($this->chapters) . ' chapters close with a takeaway',
            'key_terms' => $this->keyTerms($this->allContent(), 10),
            'arc' => 'The book opens by ' . $this->gerund((string) $this->chapters[0]['purpose'])
                . ' and closes by ' . $this->gerund((string) $this->chapters[count($this->chapters) - 1]['purpose']) . '.',
        ];
    }

    /**
     * Compare two chapters of the target book.
     *
     * @return array<string, mixed>
     */
    public function compareChapters(int $a, int $b): array
    {
        $first = $this->findChapter($a);
        $second = $this->findChapter($b);
        $termsA = $this->keyTerms((string) $first['content'], 12);
        $termsB = $this->keyTerms((string) $second['content'], 12);
        $shared = array_values(array_intersect($termsA, $termsB));
        $onlyA = array_values(array_slice(array_diff($termsA, $termsB), 0, 5));
        $onlyB = array_values(array_slice(array_diff($termsB, $termsA), 0, 5));

        return [
            'chapters' => [
                ['chapter' => (int) $first['number'], 'title' => (string) $first['title'], 'purpose' => (string) $first['purpose'], 'words' => (int) $first['word_count']],
                ['chapter' => (int) $second['number'], 'title' => (string) $second['title'], 'purpose' => (string) $second['purpose'], 'words' => (int) $second['word_count']],
            ],
            'shared_ground' => $shared === [] ? 'The two chapters share almost no vocabulary — they do different jobs.' : 'Both chapters work the same ground: ' . $this->joinList(array_slice($shared, 0, 5)) . '.',
            'distinct_emphasis' => [
                '"' . $first['title'] . '" leans on: ' . ($onlyA === [] ? 'the shared vocabulary' : $this->joinList($onlyA)),
                '"' . $second['title'] . '" leans on: ' . ($onlyB === [] ? 'the shared vocabulary' : $this->joinList($onlyB)),
            ],
            'verdict' => '"' . $first['title'] . '" exists to ' . $this->clause((string) $first['purpose'])
                . ', while "' . $second['title'] . '" exists to ' . $this->clause((string) $second['purpose'])
                . '; read them ' . ((int) $first['number'] < (int) $second['number'] ? 'in that order' : 'in book order') . ' and the second builds on the first.',
        ];
    }

    /**
     * Summary + abstract + key terms for a pasted external document.
     *
     * @return array<string, mixed>
     */
    public function documentReport(string $text, string $label = 'the document'): array
    {
        $text = trim($text);
        if ($text === '') {
            throw new InvalidArgumentException('A document needs some text before it can be summarized.');
        }
        $sentences = $this->sentences($text);
        $terms = $this->keyTerms($text, 8);
        $summary = $this->relevantSentences($text, $terms, 3);
        if ($summary === []) {
            $summary = array_slice($sentences, 0, 2);
        }
        $wordCount = count(preg_split('/\s+/u', $text) ?: []);
        return [
            'label' => $label,
            'word_count' => $wordCount,
            'sentence_count' => count($sentences),
            'summary' => $summary,
            'abstract' => ucfirst($label) . ' runs ' . $wordCount . ' words and centers on '
                . ($terms === [] ? 'its own subject' : $this->joinList(array_slice($terms, 0, 4))) . '. '
                . implode(' ', array_slice($summary, 0, 1)),
            'key_terms' => $terms,
        ];
    }

    /**
     * Compare the target book against an external document.
     *
     * @return array<string, mixed>
     */
    public function compareWithDocument(string $text, string $label = 'the supplied document'): array
    {
        $report = $this->documentReport($text, $label);
        $docTerms = $this->keyTerms($text, 15);
        $bookTerms = $this->keyTerms($this->allContent(), 15);
        $shared = array_values(array_intersect($docTerms, $bookTerms));
        $docOnly = array_values(array_slice(array_diff($docTerms, $bookTerms), 0, 5));

        $coverage = [];
        foreach ($this->chapters as $chapter) {
            $score = $this->scoreChapter($chapter, $docTerms);
            if ($score > 0) {
                $coverage[] = ['chapter' => (int) $chapter['number'], 'title' => (string) $chapter['title'], 'overlap' => $score];
            }
        }
        usort($coverage, static fn (array $a, array $b): int => $b['overlap'] <=> $a['overlap'] ?: $a['chapter'] <=> $b['chapter']);
        $coverage = array_slice($coverage, 0, 3);

        return [
            'book' => $this->title,
            'document' => $report,
            'shared_ground' => $shared === [] ? 'The document and the book barely overlap.' : 'Both cover: ' . $this->joinList(array_slice($shared, 0, 6)) . '.',
            'document_adds' => $docOnly === [] ? 'The document adds no vocabulary the book lacks.' : 'The document brings up ' . $this->joinList($docOnly) . ', which the book does not dwell on.',
            'closest_chapters' => $coverage,
            'verdict' => $coverage === []
                ? ucfirst($this->title) . ' does not really engage the ground this document covers.'
                : 'Inside ' . $this->title . ', the closest treatment is chapter ' . $coverage[0]['chapter'] . ', "' . $coverage[0]['title'] . '".',
        ];
    }

    /**
     * Suggested questions the target book can genuinely answer.
     *
     * @return array<int, string>
     */
    public function relatedQuestions(int $limit = 3): array
    {
        $questions = [];
        foreach (array_slice($this->chapters, 0, $limit) as $chapter) {
            $questions[] = 'What does "' . $chapter['title'] . '" say about how to ' . $this->clause((string) $chapter['purpose']) . '?';
        }
        return $questions;
    }

    /**
     * The book's outline: every chapter and its job.
     *
     * @return array<string, mixed>
     */
    public function outline(): array
    {
        $rows = [];
        foreach ($this->chapters as $chapter) {
            $rows[] = [
                'chapter' => (int) $chapter['number'],
                'title' => (string) $chapter['title'],
                'purpose' => ucfirst($this->clause((string) $chapter['purpose'])) . '.',
                'words' => (int) $chapter['word_count'],
                'pages' => (int) $chapter['page_count'],
            ];
        }
        return [
            'title' => $this->title,
            'chapter_count' => count($rows),
            'total_words' => $this->totalWords(),
            'chapters' => $rows,
        ];
    }

    /**
     * The book's key terms, each defined in the book's own words (the
     * shortest sentence that uses the term).
     *
     * @return array<int, array<string, string>>
     */
    public function glossary(int $limit = 10): array
    {
        $sentences = $this->sentences($this->allContent());
        $entries = [];
        foreach ($this->keyTerms($this->allContent(), $limit) as $term) {
            $definition = '';
            foreach ($sentences as $sentence) {
                if (str_contains(mb_strtolower($sentence), $term) && ($definition === '' || mb_strlen($sentence) < mb_strlen($definition))) {
                    $definition = $sentence;
                }
            }
            $entries[] = [
                'term' => $term,
                'in_the_book' => $definition !== '' ? $definition : 'A recurring concern of ' . $this->title . '.',
            ];
        }
        return $entries;
    }

    /**
     * The questions the book answers, chapter by chapter, with the answers.
     *
     * @return array<int, array<string, string>>
     */
    public function faq(): array
    {
        $entries = [];
        foreach ($this->chapters as $chapter) {
            $content = (string) $chapter['content'];
            $opening = $this->firstSentences($content, 1);
            $entries[] = [
                'question' => 'What does chapter ' . (int) $chapter['number'] . ', "' . $chapter['title'] . '", cover?',
                'answer' => $this->purposeSentence($chapter) . ($opening === [] ? '' : ' ' . $opening[0]),
            ];
            $terms = $this->keyTerms($content, 1);
            $line = $terms === [] ? [] : $this->relevantSentences($content, $terms, 1);
            if ($line !== []) {
                $entries[] = [
                    'question' => 'How does the book handle ' . $terms[0] . '?',
                    'answer' => $line[0] . ' (Chapter ' . (int) $chapter['number'] . ', "' . $chapter['title'] . '".)',
                ];
            }
        }
        return $entries;
    }

    /**
     * A study guide: per-chapter summary, key terms, discussion questions.
     *
     * @return array<int, array<string, mixed>>
     */
    public function studyGuide(): array
    {
        $guide = [];
        foreach ($this->chapters as $chapter) {
            $guide[] = [
                'chapter' => (int) $chapter['number'],
                'title' => (string) $chapter['title'],
                'summary' => $this->purposeSentence($chapter),
                'key_terms' => $this->keyTerms((string) $chapter['content'], 5),
                'discussion_questions' => [
                    'Where do you already see what "' . $chapter['title'] . '" describes in your own situation?',
                    'What would change for you if you acted on chapter ' . (int) $chapter['number'] . ' this month?',
                ],
            ];
        }
        return $guide;
    }

    /**
     * The most quotable line of every chapter, with its attribution.
     *
     * @return array<int, array<string, mixed>>
     */
    public function keyQuotes(): array
    {
        $quotes = [];
        foreach ($this->chapters as $chapter) {
            $content = (string) $chapter['content'];
            $line = $this->relevantSentences($content, $this->keyTerms($content, 6), 1);
            $quote = $line[0] ?? ($this->firstSentences($content, 1)[0] ?? '');
            if ($quote === '') {
                continue;
            }
            $quotes[] = [
                'chapter' => (int) $chapter['number'],
                'title' => (string) $chapter['title'],
                'quote' => $quote,
            ];
        }
        return $quotes;
    }

    /**
     * A session-by-session reading schedule for the whole book.
     *
     * @return array<string, mixed>
     */
    public function readingPlan(int $minutesPerSession = 45, int $wordsPerMinute = 200): array
    {
        $minutesPerSession = max(5, $minutesPerSession);
        $wordsPerMinute = max(60, $wordsPerMinute);
        $sessions = [];
        $current = ['chapters' => [], 'minutes' => 0];
        $total = 0;
        foreach ($this->chapters as $chapter) {
            $minutes = max(1, (int) ceil((int) $chapter['word_count'] / $wordsPerMinute));
            $total += $minutes;
            if ($current['chapters'] !== [] && $current['minutes'] + $minutes > $minutesPerSession) {
                $sessions[] = $current;
                $current = ['chapters' => [], 'minutes' => 0];
            }
            $current['chapters'][] = 'Chapter ' . (int) $chapter['number'] . ' — ' . $chapter['title'] . ' (' . $minutes . ' min)';
            $current['minutes'] += $minutes;
        }
        if ($current['chapters'] !== []) {
            $sessions[] = $current;
        }
        foreach ($sessions as $index => $session) {
            $sessions[$index] = ['session' => $index + 1, 'minutes' => $session['minutes'], 'chapters' => $session['chapters']];
        }
        return [
            'title' => $this->title,
            'pace' => $wordsPerMinute . ' words per minute, sessions of up to ' . $minutesPerSession . ' minutes',
            'session_count' => count($sessions),
            'total_minutes' => $total,
            'sessions' => $sessions,
        ];
    }

    /**
     * One entry point for every form of user-requested output.
     *
     * @param string $form A key of FORMS.
     * @param array<string, mixed> $options Form-specific inputs: question,
     *   mode, domain, chapter, length, max_words, chapter_a, chapter_b,
     *   document, document_label, minutes_per_session, words_per_minute, limit.
     * @return array{form:string, label:string, book:string, result:array<mixed>}
     */
    public function request(string $form, array $options = []): array
    {
        if (!isset(self::FORMS[$form])) {
            throw new InvalidArgumentException('Unknown output form "' . $form . '". Pick one of: ' . implode(', ', array_keys(self::FORMS)) . '.');
        }
        $chapter = isset($options['chapter']) && (int) $options['chapter'] > 0 ? (int) $options['chapter'] : null;
        if (in_array($form, ['compare-chapters'], true) && ((int) ($options['chapter_a'] ?? 0) <= 0 || (int) ($options['chapter_b'] ?? 0) <= 0)) {
            throw new InvalidArgumentException('Comparing chapters needs the two chapter numbers (chapter_a and chapter_b).');
        }
        if (in_array($form, ['compare-document', 'document-report'], true) && trim((string) ($options['document'] ?? '')) === '') {
            throw new InvalidArgumentException('That form needs a pasted document to work with.');
        }

        $result = match ($form) {
            'answer' => $this->ask((string) ($options['question'] ?? ''), $options),
            'summary' => $this->summarize($chapter, (string) ($options['length'] ?? 'standard')),
            'synopsis' => ['paragraphs' => $this->synopsis()],
            'abstract' => ['abstract' => $this->abstractText((int) ($options['max_words'] ?? 200))],
            'analysis' => $this->analyze($chapter),
            'outline' => $this->outline(),
            'glossary' => ['terms' => $this->glossary((int) ($options['limit'] ?? 10))],
            'faq' => ['entries' => $this->faq()],
            'study-guide' => ['chapters' => $this->studyGuide()],
            'quotes' => ['quotes' => $this->keyQuotes()],
            'reading-plan' => $this->readingPlan((int) ($options['minutes_per_session'] ?? 45), (int) ($options['words_per_minute'] ?? 200)),
            'compare-chapters' => $this->compareChapters((int) $options['chapter_a'], (int) $options['chapter_b']),
            'compare-document' => $this->compareWithDocument((string) $options['document'], (string) ($options['document_label'] ?? 'the supplied document')),
            'document-report' => $this->documentReport((string) $options['document'], (string) ($options['document_label'] ?? 'the document')),
            'related-questions' => ['questions' => $this->relatedQuestions((int) ($options['limit'] ?? 5))],
        };
        return ['form' => $form, 'label' => self::FORMS[$form], 'book' => $this->title, 'result' => $result];
    }

    /** Render any request() result as portable Markdown. */
    public function renderMarkdown(array $request): string
    {
        $md = '# ' . (string) ($request['label'] ?? 'QueryBook') . "\n\n"
            . 'Target book: ' . $this->title . "\n\n"
            . $this->markdownValue($request['result'] ?? [], 2);
        return trim(preg_replace("/\n{3,}/", "\n\n", $md) ?? $md) . "\n";
    }

    /** Render any request() result as plain text. */
    public function renderPlainText(array $request): string
    {
        $text = $this->renderMarkdown($request);
        $text = preg_replace('/^#{1,6}\s*/m', '', $text) ?? $text;
        $text = preg_replace('/^\-\s/m', '  • ', $text) ?? $text;
        return str_replace('**', '', $text);
    }

    // -- internals -----------------------------------------------------------

    /** Recursive Markdown rendering for any deliverable's payload. */
    private function markdownValue(mixed $value, int $depth): string
    {
        if (is_scalar($value) || $value === null) {
            $line = trim((string) $value);
            return $line === '' ? '' : $line . "\n\n";
        }
        $value = (array) $value;
        if ($value === []) {
            return '';
        }
        if (array_is_list($value)) {
            $out = '';
            foreach ($value as $item) {
                $out .= is_scalar($item) || $item === null
                    ? '- ' . trim((string) $item) . "\n"
                    : $this->markdownValue($item, $depth + 1);
            }
            return $out . "\n";
        }
        $out = '';
        foreach ($value as $key => $item) {
            $label = ucfirst(str_replace(['_', '-'], ' ', (string) $key));
            if (is_scalar($item) || $item === null) {
                $out .= '**' . $label . ':** ' . trim((string) $item) . "\n\n";
            } else {
                $out .= str_repeat('#', min(6, $depth)) . ' ' . $label . "\n\n" . $this->markdownValue($item, $depth + 1);
            }
        }
        return $out;
    }

    /** @return array<string, mixed> */
    private function findChapter(int $number): array
    {
        foreach ($this->chapters as $chapter) {
            if ((int) $chapter['number'] === $number) {
                return $chapter;
            }
        }
        throw new InvalidArgumentException('The book has no chapter ' . $number . '.');
    }

    /** @return array<int, string> Lowercased content words, stopwords removed. */
    private function tokenize(string $text): array
    {
        preg_match_all('/[\p{L}\p{N}][\p{L}\p{N}\'-]*/u', mb_strtolower($text), $matches);
        $terms = [];
        foreach ($matches[0] as $word) {
            if (mb_strlen($word) >= 3 && !in_array($word, self::STOPWORDS, true)) {
                $terms[] = $word;
            }
        }
        return array_values(array_unique($terms));
    }

    /** @param array<int, string> $terms */
    private function scoreChapter(array $chapter, array $terms): int
    {
        if ($terms === []) {
            return 0;
        }
        $title = mb_strtolower((string) $chapter['title']);
        $purpose = mb_strtolower((string) $chapter['purpose'] . ' ' . (string) ($chapter['detail'] ?? ''));
        $content = mb_strtolower((string) $chapter['content']);
        $score = 0;
        foreach ($terms as $term) {
            if (str_contains($title, $term)) {
                $score += 4;
            }
            if (str_contains($purpose, $term)) {
                $score += 2;
            }
            $score += min(3, substr_count($content, $term));
        }
        return $score;
    }

    /** @return array<int, string> */
    private function sentences(string $text): array
    {
        // Headings (chapter and section titles) live on their own lines and
        // carry no closing punctuation — drop them so they never bleed into
        // an extracted sentence.
        $lines = array_filter(
            array_map('trim', preg_split('/\R/u', $text) ?: []),
            static fn (string $line): bool => (bool) preg_match('/[.!?…"”\']$/u', $line),
        );
        $flat = trim(preg_replace('/\s+/u', ' ', implode(' ', $lines)) ?? '');
        if ($flat === '') {
            return [];
        }
        $parts = preg_split('/(?<=[.!?])\s+(?=[\p{Lu}"“])/u', $flat) ?: [];
        return array_values(array_filter(array_map('trim', $parts), static fn (string $s): bool => mb_strlen($s) >= 20));
    }

    /**
     * The sentences of $text that carry the most query terms, in text order.
     *
     * @param array<int, string> $terms
     * @return array<int, string>
     */
    private function relevantSentences(string $text, array $terms, int $limit): array
    {
        $scored = [];
        foreach ($this->sentences($text) as $index => $sentence) {
            $lower = mb_strtolower($sentence);
            $hits = 0;
            foreach ($terms as $term) {
                if (str_contains($lower, $term)) {
                    $hits++;
                }
            }
            if ($hits > 0) {
                $scored[] = ['index' => $index, 'hits' => $hits, 'sentence' => $sentence];
            }
        }
        usort($scored, static fn (array $a, array $b): int => $b['hits'] <=> $a['hits'] ?: $a['index'] <=> $b['index']);
        $picked = array_slice($scored, 0, $limit);
        usort($picked, static fn (array $a, array $b): int => $a['index'] <=> $b['index']);
        return array_column($picked, 'sentence');
    }

    /** @return array<int, string> */
    private function firstSentences(string $text, int $limit): array
    {
        return array_slice($this->sentences($text), 0, $limit);
    }

    /**
     * Most frequent meaningful words of $text, ties broken alphabetically.
     *
     * @return array<int, string>
     */
    private function keyTerms(string $text, int $limit): array
    {
        preg_match_all('/[\p{L}][\p{L}\'-]{3,}/u', mb_strtolower($text), $matches);
        $counts = [];
        foreach ($matches[0] as $word) {
            if (!in_array($word, self::STOPWORDS, true)) {
                $counts[$word] = ($counts[$word] ?? 0) + 1;
            }
        }
        uksort($counts, static fn (string $a, string $b): int => $counts[$b] <=> $counts[$a] ?: strcmp($a, $b));
        return array_slice(array_keys($counts), 0, $limit);
    }

    private function purposeSentence(array $chapter): string
    {
        return 'The chapter\'s job in the book is to ' . $this->clause((string) $chapter['purpose']) . '.';
    }

    /** Lowercase a purpose/detail clause and strip its trailing period. */
    private function clause(string $text): string
    {
        $text = trim($text);
        $text = rtrim($text, '.');
        return $text === '' ? 'move the argument forward' : lcfirst($text);
    }

    /** "Explain the market" → "explaining the market" (best-effort, deterministic). */
    private function gerund(string $purpose): string
    {
        $clause = $this->clause($purpose);
        $words = explode(' ', $clause, 2);
        $verb = $words[0];
        $rest = $words[1] ?? '';
        if (str_ends_with($verb, 'ie')) {
            $verb = substr($verb, 0, -2) . 'ying';
        } elseif (str_ends_with($verb, 'e') && !str_ends_with($verb, 'ee')) {
            $verb = substr($verb, 0, -1) . 'ing';
        } else {
            $verb .= 'ing';
        }
        return trim($verb . ' ' . $rest);
    }

    /** @param array<int, string> $items */
    private function joinList(array $items): string
    {
        $items = array_values($items);
        if ($items === []) {
            return '';
        }
        if (count($items) === 1) {
            return $items[0];
        }
        $last = array_pop($items);
        return implode(', ', $items) . ' and ' . $last;
    }

    private function totalWords(): int
    {
        return (int) array_sum(array_map(static fn (array $c): int => (int) $c['word_count'], $this->chapters));
    }

    private function allContent(): string
    {
        return implode("\n\n", array_map(static fn (array $c): string => (string) $c['content'], $this->chapters));
    }
}
