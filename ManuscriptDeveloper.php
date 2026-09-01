<?php

declare(strict_types=1);

/**
 * Manuscript Developer
 *
 * The first-run engine draft is a set of development directions — an outline
 * with per-chapter purpose and detail. This class turns that plan into the
 * jobs an AI writer executes so the FIRST RUN of the pipeline ends in real
 * book prose instead of directions-as-text:
 *
 *   pass 1 (engine)  — outline + per-chapter draft directions (deterministic)
 *   pass 2 (writer)  — one AI job per chapter follows its directions and
 *                      writes the finished prose
 *   pass 3 (editor)  — one AI job per chapter sweeps for repetition,
 *                      transitions, and format compliance
 *
 * Like the Illustration Studio's image manifest, everything here is a
 * deterministic plan: prompts and HTTPS request specs for Anthropic Claude,
 * Google Gemini, or OpenAI. The `bin/develop-manuscript.php` CLI executes the
 * plan with an API key and assembles the developed chapters back into the
 * book (dependency-free raw HTTP by project constraint — no Composer).
 */
final class ManuscriptDeveloper
{
    public const PROVIDERS = ['anthropic', 'google', 'openai'];

    public const DEFAULT_MODELS = [
        'anthropic' => 'claude-opus-5',
        'google' => 'gemini-2.5-pro',
        'openai' => 'gpt-4o',
    ];

    public const KEY_ENV = [
        'anthropic' => 'ANTHROPIC_API_KEY',
        'google' => 'GOOGLE_AI_API_KEY',
        'openai' => 'OPENAI_API_KEY',
    ];

    /** Narrative person options for the voice contract. */
    public const NARRATIVE_VOICES = [
        'third-person' => 'Third person — the narrator writes about people and events from outside ("he", "she", "they"); the author never says "I".',
        'first-person' => 'First person singular — the author speaks as "I" throughout, telling, remembering, and arguing from their own standpoint.',
        'first-person-plural' => 'First person plural — the author speaks as "we", placing themselves and the reader inside a shared experience.',
        'second-person' => 'Second person — the text addresses the reader directly as "you" throughout.',
    ];

    /** Perspective factors that shape the voice contract. */
    public const PERSPECTIVE_FACTORS = [
        'emotional-testimony' => 'Emotional testimony: real feeling shows on the page — grief, anger, longing, hope — testified to honestly rather than reported at arm\'s length.',
        'subjective-bias' => 'Openly subjective: the author holds a stated point of view and argues it with conviction; the text never pretends to neutrality.',
        'experiential' => 'Experiential: lived experience carries the argument — scenes, memories, sensory detail, and firsthand observation before abstraction.',
        'objective' => 'Objective and evidence-led: claims rest on evidence, presented plainly; personal feeling stays out of the way of the facts.',
        'highly-technical' => 'Highly technical: precise terminology, mechanisms, and exact reasoning; assumes a reader who wants rigor over comfort.',
        'detached-observant' => 'Detached and observant: a cool, watchful narrator who describes exactly what is there and lets the reader draw the conclusions.',
    ];

    /**
     * The full development plan for a generated book: the style contract and
     * one writer + one editor job per chapter.
     *
     * @param array<string, mixed> $book Output of generateBookFromTableOfContents().
     * @param array<string, mixed> $metadata Listing metadata (title, subtitle, author, audience…).
     * @return array<string, mixed>
     */
    public function developmentPlan(array $book, array $metadata, string $provider = 'anthropic', array $options = []): array
    {
        if (!in_array($provider, self::PROVIDERS, true)) {
            throw new InvalidArgumentException('Unknown provider: ' . $provider);
        }
        $model = trim((string) ($options['model'] ?? '')) ?: self::DEFAULT_MODELS[$provider];
        $contract = $this->styleContract($book, $metadata);
        $chapters = array_values((array) ($book['chapters'] ?? []));

        $writerJobs = [];
        $editorJobs = [];
        foreach ($chapters as $index => $chapter) {
            $number = (int) ($chapter['number'] ?? ($index + 1));
            $file = sprintf('chapter-%02d.txt', $number);
            $writerPrompt = $this->writerPrompt($chapter, $contract);
            $writerJobs[] = [
                'chapter' => $number,
                'title' => (string) ($chapter['title'] ?? ''),
                'word_target' => (int) ($chapter['word_count'] ?? 2500),
                'output_file' => $file,
                'prompt' => $writerPrompt,
                'request' => $this->requestSpec($provider, $model, $contract, $writerPrompt),
            ];
            $previous = $index > 0 ? $chapters[$index - 1] : null;
            $next = $index < count($chapters) - 1 ? $chapters[$index + 1] : null;
            $editorJobs[] = [
                'chapter' => $number,
                'input_file' => $file,
                'output_file' => sprintf('edited/chapter-%02d.txt', $number),
                'prompt_template' => $this->editorPrompt($chapter, $previous, $next),
                'note' => 'Replace {CHAPTER_TEXT}, {PREVIOUS_CLOSE}, and {NEXT_OPEN} with the drafted texts before sending.',
            ];
        }

        return [
            'provider' => $provider,
            'model' => $model,
            'key_env' => self::KEY_ENV[$provider],
            'style_contract' => $contract,
            'writer_jobs' => $writerJobs,
            'editor_jobs' => $editorJobs,
            'job_count' => count($writerJobs) + count($editorJobs),
            'notes' => 'Run bin/develop-manuscript.php to execute this plan and assemble the developed book, or send each prompt to your own AI tooling and save the replies under the output file names.',
        ];
    }

    /**
     * The shared writing contract every chapter job carries — built from the
     * book itself so any topic gets a coherent single-voice brief.
     *
     * @param array<string, mixed> $book
     * @param array<string, mixed> $metadata
     */
    public function styleContract(array $book, array $metadata): string
    {
        $title = trim((string) ($metadata['title'] ?? 'the book')) ?: 'the book';
        $author = trim((string) ($metadata['author'] ?? 'the author')) ?: 'the author';
        $audience = trim((string) ($metadata['audience'] ?? '')) ?: 'curious readers';
        $styleLabel = trim((string) ($book['style_label'] ?? 'Conversational'));
        $description = trim((string) ($metadata['description'] ?? ''));
        $tocLines = [];
        foreach ((array) ($book['chapters'] ?? []) as $chapter) {
            $tocLines[] = ((int) ($chapter['number'] ?? 0)) . '. ' . (string) ($chapter['title'] ?? '');
        }

        $voice = (array) ($book['voice'] ?? []);
        $narrative = self::NARRATIVE_VOICES[(string) ($voice['narrative'] ?? '')] ?? self::NARRATIVE_VOICES['third-person'];
        $voiceLines = ["- Narrative person: {$narrative} Hold this grammatical person in every paragraph of every chapter — never drift."];
        foreach ((array) ($voice['perspectives'] ?? []) as $factor) {
            if (isset(self::PERSPECTIVE_FACTORS[(string) $factor])) {
                $voiceLines[] = '- ' . self::PERSPECTIVE_FACTORS[(string) $factor];
            }
        }
        $authorVoice = trim((string) ($voice['author_voice'] ?? ''));
        if ($authorVoice !== '') {
            $voiceLines[] = "- The author's own voice, in their words: {$authorVoice}. Write as this person would write.";
        }
        $voiceLines[] = '- When these factors pull against each other, blend them deliberately — never abandon one.';

        return "You are one of a team of writers producing the finished prose of the book \"{$title}\" by {$author}.\n"
            . "The first draft was a set of development directions; your job is to FOLLOW those directions and write the real chapter — legitimate book text a reader would buy. Voice: {$styleLabel}. Reader: {$audience}.\n"
            . ($description !== '' ? "About the book: {$description}\n" : '')
            . "The chapters (stay in your lane — each theme belongs to its chapter):\n" . implode("\n", $tocLines) . "\n"
            . "VOICE CONTRACT (a MUST — voice accuracy is a hard requirement of this book; no rule below overrides it):\n"
            . implode("\n", $voiceLines) . "\n"
            . "HARD RULES:\n"
            . "1. Real prose only. Never write about outlines, drafts, plans, purposes, \"this chapter\", \"this book\", or how the text is built. The text discusses its subject — never the writing of it.\n"
            . "2. Follow the chapter's draft directions (its purpose and detail). Every element listed in the detail must appear, developed, in the chapter.\n"
            . "3. No fabricated precision. Use well-established, widely reported facts; refer to sources generically (\"national surveys\", \"census figures\") and hedge magnitudes rather than inventing exact statistics, named fake studies, or verbatim quotes. Never invent a named expert or a quotation from a real person.\n"
            . "4. Composite ordinary people with plain first names may carry scenes; keep history accurate.\n"
            . "5. Fair-minded and committed: argue the book's thesis with conviction while crediting good faith on all sides.\n"
            . "FORMAT (exact — a parser assembles the book from this): plain text; first line exactly `Chapter N: <Title>`; blank line between every paragraph; no single line-breaks inside a paragraph; no markdown, bullets, or numbered lists; 4–8 short section subheadings (under 60 characters, no ending period) on their own lines with blank lines around them; the final section is exactly the heading `The takeaway` followed by one short paragraph; hit the word target within ±10%; paragraphs 60–130 words; open with a scene or a sharp claim.";
    }

    /**
     * The pass-2 writing prompt for one chapter.
     *
     * @param array<string, mixed> $chapter
     */
    public function writerPrompt(array $chapter, string $contract): string
    {
        $number = (int) ($chapter['number'] ?? 0);
        $title = (string) ($chapter['title'] ?? '');
        $purpose = (string) ($chapter['purpose'] ?? '');
        $detail = (string) ($chapter['detail'] ?? '');
        $words = (int) ($chapter['word_count'] ?? 2500);

        return "Write chapter {$number} of the book: \"{$title}\".\n"
            . "Draft directions to follow — purpose: {$purpose}\n"
            . "Draft directions to follow — detail: {$detail}\n"
            . "Word target: {$words} words (±10%).\n"
            . "Follow the writing contract exactly. Reply with ONLY the finished chapter text, beginning with the line `Chapter {$number}: {$title}`.";
    }

    /**
     * The pass-3 editing prompt template for one chapter.
     *
     * @param array<string, mixed> $chapter
     * @param array<string, mixed>|null $previous
     * @param array<string, mixed>|null $next
     */
    public function editorPrompt(array $chapter, ?array $previous, ?array $next): string
    {
        $number = (int) ($chapter['number'] ?? 0);
        $title = (string) ($chapter['title'] ?? '');

        return "You are the line editor for chapter {$number} (\"{$title}\") of the book. Revise the drafted chapter below and reply with ONLY the revised chapter text, keeping the first line `Chapter {$number}: {$title}` and the exact format rules from the writing contract.\n"
            . "Edit for: (a) removing anything that reads as writing directions instead of book prose; (b) repetition of neighboring chapters' territory — "
            . ($previous !== null ? 'the previous chapter covered "' . (string) ($previous['title'] ?? '') . '"; ' : '')
            . ($next !== null ? 'the next chapter covers "' . (string) ($next['title'] ?? '') . '"; ' : '')
            . "(c) a closing that hands off naturally to what follows; (d) hedging any too-precise statistic and removing any invented named expert or quote; (e) flab; (f) ANY drift from the VOICE CONTRACT — the narrative person and perspective are a hard requirement, so rewrite any sentence that breaks them.\n"
            . ($previous !== null ? "The previous chapter closes with:\n{PREVIOUS_CLOSE}\n" : '')
            . ($next !== null ? "The next chapter opens with:\n{NEXT_OPEN}\n" : '')
            . "The drafted chapter:\n{CHAPTER_TEXT}";
    }

    /**
     * Provider-specific HTTPS request description for one prompt. The key is
     * never embedded — the CLI injects it from the environment at send time.
     *
     * @return array<string, mixed>
     */
    public function requestSpec(string $provider, string $model, string $system, string $prompt): array
    {
        return match ($provider) {
            'anthropic' => [
                'endpoint' => 'https://api.anthropic.com/v1/messages',
                'method' => 'POST',
                'headers' => ['content-type' => 'application/json', 'anthropic-version' => '2023-06-01', 'x-api-key' => '{' . self::KEY_ENV['anthropic'] . '}'],
                'body' => [
                    'model' => $model,
                    'max_tokens' => 16000,
                    'system' => $system,
                    'messages' => [['role' => 'user', 'content' => $prompt]],
                ],
            ],
            'google' => [
                'endpoint' => 'https://generativelanguage.googleapis.com/v1beta/models/' . $model . ':generateContent',
                'method' => 'POST',
                'headers' => ['content-type' => 'application/json', 'x-goog-api-key' => '{' . self::KEY_ENV['google'] . '}'],
                'body' => [
                    'systemInstruction' => ['parts' => [['text' => $system]]],
                    'contents' => [['role' => 'user', 'parts' => [['text' => $prompt]]]],
                    'generationConfig' => ['maxOutputTokens' => 16000],
                ],
            ],
            'openai' => [
                'endpoint' => 'https://api.openai.com/v1/chat/completions',
                'method' => 'POST',
                'headers' => ['content-type' => 'application/json', 'authorization' => 'Bearer {' . self::KEY_ENV['openai'] . '}'],
                'body' => [
                    'model' => $model,
                    'max_completion_tokens' => 16000,
                    'messages' => [
                        ['role' => 'system', 'content' => $system],
                        ['role' => 'user', 'content' => $prompt],
                    ],
                ],
            ],
            default => throw new InvalidArgumentException('Unknown provider: ' . $provider),
        };
    }

    /**
     * Pull the generated text out of a provider's JSON response.
     *
     * @param array<string, mixed> $response Decoded JSON.
     */
    public function extractText(string $provider, array $response): string
    {
        if ($provider === 'anthropic') {
            $parts = [];
            foreach ((array) ($response['content'] ?? []) as $block) {
                if (($block['type'] ?? '') === 'text') {
                    $parts[] = (string) ($block['text'] ?? '');
                }
            }
            return trim(implode("\n", $parts));
        }
        if ($provider === 'google') {
            $parts = [];
            foreach ((array) ($response['candidates'][0]['content']['parts'] ?? []) as $part) {
                if (isset($part['text'])) {
                    $parts[] = (string) $part['text'];
                }
            }
            return trim(implode("\n", $parts));
        }
        return trim((string) ($response['choices'][0]['message']['content'] ?? ''));
    }

    /**
     * Execute one request spec against its provider. The API key replaces the
     * `{ENV_NAME}` placeholder in the headers at send time. Dependency-free:
     * uses ext-curl when present, PHP's HTTPS stream wrapper otherwise.
     *
     * @param array<string, mixed> $spec Output of requestSpec().
     * @return array<string, mixed> Decoded JSON response.
     */
    public function send(array $spec, string $key, int $attempts = 4): array
    {
        $payload = json_encode((array) ($spec['body'] ?? []), JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        if ($payload === false) {
            throw new RuntimeException('Could not encode the request body.');
        }
        $headerLines = [];
        foreach ((array) ($spec['headers'] ?? []) as $name => $value) {
            $headerLines[] = $name . ': ' . preg_replace('/\{[A-Z_]+\}/', $key, (string) $value);
        }
        $url = (string) ($spec['endpoint'] ?? '');
        $attempt = 0;
        while (true) {
            $attempt++;
            if (function_exists('curl_init')) {
                $ch = curl_init($url);
                curl_setopt_array($ch, [
                    CURLOPT_POST => true,
                    CURLOPT_POSTFIELDS => $payload,
                    CURLOPT_HTTPHEADER => $headerLines,
                    CURLOPT_RETURNTRANSFER => true,
                    CURLOPT_TIMEOUT => 600,
                ]);
                $raw = curl_exec($ch);
                $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
                $error = (string) curl_error($ch);
                curl_close($ch);
            } else {
                $context = stream_context_create(['http' => [
                    'method' => 'POST',
                    'header' => implode("\r\n", $headerLines),
                    'content' => $payload,
                    'timeout' => 600,
                    'ignore_errors' => true,
                ]]);
                $raw = @file_get_contents($url, false, $context);
                $status = 0;
                foreach ($http_response_header ?? [] as $line) {
                    if (preg_match('#^HTTP/\S+\s+(\d{3})#', $line, $m) === 1) {
                        $status = (int) $m[1];
                    }
                }
                $error = $raw === false ? 'connection failed' : '';
            }
            if ($raw !== false && $status >= 200 && $status < 300) {
                $decoded = json_decode((string) $raw, true);
                if (is_array($decoded)) {
                    return $decoded;
                }
                $error = 'response was not JSON';
            }
            $retryable = $raw === false || $status === 429 || $status >= 500;
            if ($attempt >= $attempts || !$retryable) {
                throw new RuntimeException('API call failed (HTTP ' . $status . ($error !== '' ? ', ' . $error : '') . '): ' . substr((string) $raw, 0, 400));
            }
            sleep(2 ** $attempt);
        }
    }

    /**
     * Develop one chapter now: send its writer job and return the prose,
     * with the chapter heading guaranteed on the first line.
     *
     * @param array<string, mixed> $job A writer_jobs entry from developmentPlan().
     */
    public function developChapterText(string $provider, array $job, string $key, int $attempts = 4): string
    {
        $response = $this->send((array) $job['request'], $key, $attempts);
        $text = $this->extractText($provider, $response);
        if ($text === '') {
            throw new RuntimeException('The AI writer returned no text for chapter ' . (int) ($job['chapter'] ?? 0) . '.');
        }
        if (!str_starts_with(trim($text), 'Chapter ')) {
            $text = 'Chapter ' . (int) ($job['chapter'] ?? 0) . ': ' . (string) ($job['title'] ?? '') . "\n\n" . trim($text);
        }
        return trim($text);
    }

    /**
     * Swap developed chapter texts into a generated book: content, blocks,
     * word counts, page counts, and the contents page numbers all recompute.
     *
     * @param array<string, mixed> $book
     * @param array<int, string> $chapterTexts Chapter number => finished text.
     * @return array<string, mixed>
     */
    public function applyDevelopedChapters(array $book, array $chapterTexts): array
    {
        $totalWords = 0;
        foreach ((array) ($book['chapters'] ?? []) as $i => $chapter) {
            $number = (int) ($chapter['number'] ?? 0);
            if (isset($chapterTexts[$number]) && trim((string) $chapterTexts[$number]) !== '') {
                $content = trim((string) $chapterTexts[$number]);
                $content = trim(preg_replace('/\R{3,}/u', "\n\n", preg_replace('/[ \t]+$/m', '', $content) ?? $content) ?? $content);
                $book['chapters'][$i]['content'] = $content;
                $book['chapters'][$i]['blocks'] = $this->blocksFor($content);
            }
            preg_match_all('/\S+/u', (string) $book['chapters'][$i]['content'], $m);
            $words = count($m[0]);
            $book['chapters'][$i]['word_count'] = $words;
            $book['chapters'][$i]['page_count'] = max(1, (int) ceil($words / 250));
            $totalWords += $words;
        }
        $book['total_word_count'] = $totalWords;
        $book['page_count'] = array_sum(array_column((array) $book['chapters'], 'page_count'));
        $toc = [];
        $nextPage = 3;
        foreach ((array) $book['chapters'] as $chapter) {
            $toc[] = [
                'number' => $chapter['number'],
                'title' => $chapter['title'],
                'purpose' => $chapter['purpose'],
                'page_count' => $chapter['page_count'],
                'word_count' => $chapter['word_count'],
                'page_number' => $nextPage,
            ];
            $nextPage += (int) $chapter['page_count'];
        }
        $book['table_of_contents'] = $toc;
        return $book;
    }

    /**
     * Project developed prose into the block vocabulary the exporters read —
     * the same segmentation the engine applies to its own drafts.
     *
     * @return array<int, array<string, mixed>>
     */
    private function blocksFor(string $content): array
    {
        $chunks = preg_split('/\R{2,}/u', trim($content), -1, PREG_SPLIT_NO_EMPTY) ?: [];
        $blocks = [];
        foreach ($chunks as $index => $chunk) {
            $chunk = trim($chunk);
            if ($chunk === '') {
                continue;
            }
            $isChapterHeading = $index === 0 && preg_match('/^chapter\s+\d+/i', $chunk) === 1;
            $blocks[] = [
                'id' => 'php-block-' . ($index + 1),
                'kind' => $isChapterHeading ? 'heading' : 'paragraph',
                'level' => $isChapterHeading ? 1 : null,
                'content' => $chunk,
            ];
        }
        if ($blocks === []) {
            $blocks[] = ['id' => 'php-block-1', 'kind' => 'paragraph', 'level' => null, 'content' => $content];
        }
        return $blocks;
    }
}
