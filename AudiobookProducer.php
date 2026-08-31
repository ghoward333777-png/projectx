<?php

declare(strict_types=1);

/**
 * Audiobook Producer
 *
 * Turns a generated manuscript into an audiobook production package:
 * a narration script (opening credits, chapters, closing credits),
 * provider-sized synthesis chunks, ready-to-send request payloads for
 * Google Cloud Text-to-Speech and ElevenLabs, a job manifest for a
 * local voice-cloning engine, runtime and cost estimates, and the
 * ACX/Audible delivery specs.
 *
 * Voice cloning uses a sampled human recording. Cloning a voice
 * requires the recorded speaker's explicit consent: any provider mode
 * that clones from a sample refuses to build jobs until the caller
 * confirms consent. This is a hard gate, not a formality.
 *
 * Like the rest of the app this class is deterministic and offline —
 * it prepares payloads and estimates; the bin/synthesize-audiobook.php
 * CLI performs the actual API calls with the user's own keys.
 */
final class AudiobookProducer
{
    public const PROVIDERS = ['google', 'elevenlabs', 'local-clone'];

    /** Finished-hour pacing commonly used for audiobook planning. */
    public const WORDS_PER_FINISHED_HOUR = 9300;

    /** Google Cloud TTS caps synthesize requests at 5,000 bytes; leave headroom. */
    public const GOOGLE_MAX_CHUNK_CHARS = 4500;

    /** ElevenLabs standard per-request text limit headroom. */
    public const ELEVENLABS_MAX_CHUNK_CHARS = 4500;

    /** Local cloning engines (XTTS-style) prefer shorter utterances. */
    public const LOCAL_CLONE_MAX_CHUNK_CHARS = 1200;

    /** Directional per-million-character synthesis rates in USD. */
    private const COST_PER_MILLION_CHARS = [
        'google' => 16.0,      // Neural2 / WaveNet tier
        'elevenlabs' => 150.0, // typical Creator-plan effective rate
        'local-clone' => 0.0,  // your own compute
    ];

    private const PROVIDER_LABELS = [
        'google' => 'Google Cloud Text-to-Speech',
        'elevenlabs' => 'ElevenLabs',
        'local-clone' => 'Internal voice-cloning engine (sampled recording)',
    ];

    /**
     * Default voice settings per provider; all overridable via options.
     *
     * @return array<string, array<string, mixed>>
     */
    public function defaultVoices(): array
    {
        return [
            'google' => [
                'language_code' => 'en-US',
                'voice_name' => 'en-US-Neural2-D',
                'speaking_rate' => 0.97,
                'pitch' => 0.0,
                'audio_encoding' => 'MP3',
            ],
            'elevenlabs' => [
                'voice_id' => 'narrator',
                'model_id' => 'eleven_multilingual_v2',
                'stability' => 0.5,
                'similarity_boost' => 0.75,
                'output_format' => 'mp3_44100_192',
            ],
            'local-clone' => [
                'engine' => 'xtts',
                'language' => 'en',
                'sample_path' => '',
                'output_format' => 'wav_44100',
            ],
        ];
    }

    /**
     * Whether the provider mode clones a sampled human voice (and therefore
     * requires the speaker's consent before any job is produced).
     */
    public function requiresCloneConsent(string $provider, array $voice = []): bool
    {
        if ($provider === 'local-clone') {
            return true;
        }
        if ($provider === 'elevenlabs') {
            return !empty($voice['cloned_from_sample']) || !empty($voice['clone_sample_path']);
        }
        return false;
    }

    /**
     * Build the narration script: credits plus one entry per chapter.
     *
     * @param array<string, mixed> $book Output of BookIntelligenceEngine::generateBookFromTableOfContents().
     * @param array<string, mixed> $metadata Listing metadata (title, subtitle, author).
     * @return array{opening_credits:string, chapters:array<int, array{number:int, title:string, text:string, word_count:int}>, closing_credits:string, total_word_count:int}
     */
    public function narrationScript(array $book, array $metadata): array
    {
        $title = trim((string) ($metadata['title'] ?? 'Untitled'));
        $subtitle = trim((string) ($metadata['subtitle'] ?? ''));
        $author = trim((string) ($metadata['author'] ?? 'the author')) ?: 'the author';

        $opening = $title . ($subtitle !== '' ? '. ' . $subtitle : '') . '. Written by ' . $author . '.';
        $closing = 'This has been ' . $title . ', written by ' . $author . '. Thank you for listening.';

        $chapters = [];
        $totalWords = 0;
        foreach ((array) ($book['chapters'] ?? []) as $chapter) {
            $text = $this->narrationTextForChapter($chapter);
            $words = $this->wordCount($text);
            $totalWords += $words;
            $chapters[] = [
                'number' => (int) ($chapter['number'] ?? 0),
                'title' => (string) ($chapter['title'] ?? ''),
                'text' => $text,
                'word_count' => $words,
            ];
        }
        $totalWords += $this->wordCount($opening) + $this->wordCount($closing);

        return [
            'opening_credits' => $opening,
            'chapters' => $chapters,
            'closing_credits' => $closing,
            'total_word_count' => $totalWords,
        ];
    }

    /**
     * Split text into synthesis-sized chunks on sentence boundaries.
     *
     * @return array<int, string>
     */
    public function chunkText(string $text, int $limit): array
    {
        $limit = max(200, $limit);
        $sentences = preg_split('/(?<=[.!?])\s+/u', trim($text), -1, PREG_SPLIT_NO_EMPTY) ?: [];
        $chunks = [];
        $current = '';
        foreach ($sentences as $sentence) {
            // A single sentence longer than the limit is split hard at word
            // boundaries so no request can exceed the provider cap.
            while (mb_strlen($sentence) > $limit) {
                $slice = mb_substr($sentence, 0, $limit);
                $cut = (int) max((int) mb_strrpos($slice, ' '), (int) ($limit * 0.5));
                if ($current !== '') {
                    $chunks[] = $current;
                    $current = '';
                }
                $chunks[] = trim(mb_substr($sentence, 0, $cut));
                $sentence = trim(mb_substr($sentence, $cut));
            }
            $candidate = $current === '' ? $sentence : $current . ' ' . $sentence;
            if (mb_strlen($candidate) > $limit) {
                $chunks[] = $current;
                $current = $sentence;
            } else {
                $current = $candidate;
            }
        }
        if (trim($current) !== '') {
            $chunks[] = trim($current);
        }
        return array_values(array_filter($chunks, static fn (string $c): bool => trim($c) !== ''));
    }

    /**
     * Full production plan: runtime, chunking, costs, specs, and consent state.
     *
     * @param array<string, mixed> $book
     * @param array<string, mixed> $metadata
     * @param array<string, mixed> $options Supports: voice (per-provider overrides),
     *   voice_consent (bool — the sampled speaker consented to cloning).
     * @return array<string, mixed>
     */
    public function plan(array $book, array $metadata, string $provider = 'google', array $options = []): array
    {
        $provider = in_array($provider, self::PROVIDERS, true) ? $provider : 'google';
        $voice = array_merge($this->defaultVoices()[$provider], is_array($options['voice'] ?? null) ? $options['voice'] : []);
        $script = $this->narrationScript($book, $metadata);
        $limit = $this->chunkLimit($provider);

        $chunkCount = count($this->chunkText($script['opening_credits'], $limit))
            + count($this->chunkText($script['closing_credits'], $limit));
        $charCount = mb_strlen($script['opening_credits']) + mb_strlen($script['closing_credits']);
        foreach ($script['chapters'] as $chapter) {
            $chunkCount += count($this->chunkText($chapter['text'], $limit));
            $charCount += mb_strlen($chapter['text']);
        }

        $runtimeHours = round($script['total_word_count'] / self::WORDS_PER_FINISHED_HOUR, 1);
        $synthesisCost = round(($charCount / 1_000_000) * self::COST_PER_MILLION_CHARS[$provider], 2);
        $needsConsent = $this->requiresCloneConsent($provider, $voice);
        $hasConsent = (bool) ($options['voice_consent'] ?? false);

        return [
            'provider' => $provider,
            'provider_label' => self::PROVIDER_LABELS[$provider],
            'voice' => $voice,
            'runtime_estimate_hours' => max(0.1, $runtimeHours),
            'total_word_count' => $script['total_word_count'],
            'total_char_count' => $charCount,
            'chunk_count' => $chunkCount,
            'chunk_char_limit' => $limit,
            'estimated_synthesis_cost_usd' => $synthesisCost,
            'clone_consent' => [
                'required' => $needsConsent,
                'confirmed' => $hasConsent,
                'status' => !$needsConsent
                    ? 'Not required — no human voice is being cloned.'
                    : ($hasConsent
                        ? 'Confirmed — the recorded speaker has consented to voice cloning.'
                        : 'BLOCKED — voice cloning from a sampled recording requires the speaker\'s explicit consent before any job is produced.'),
            ],
            'suggested_retail' => $this->suggestedRetail($runtimeHours),
            'acx_specs' => [
                'format' => '192 kbps CBR MP3, 44.1 kHz, one file per chapter',
                'loudness' => 'RMS between -23 dB and -18 dB, peaks at or below -3 dB',
                'room_tone' => '0.5–1 second of room tone at the head and tail of each file',
                'noise_floor' => 'Noise floor at or below -60 dB RMS',
                'credits' => 'Opening and closing credits required; retail sample of 1–5 minutes',
            ],
            'workflow' => [
                'Generate the narration script and synthesis manifest below.',
                'Run bin/synthesize-audiobook.php with your API key (or local engine) to produce per-chunk audio.',
                'Concatenate chunks per chapter (ffmpeg) and master to the ACX loudness specs.',
                'Upload chapter files plus the retail sample to ACX/Audible or KDP Virtual Voice.',
            ],
        ];
    }

    /**
     * Per-chunk synthesis manifest with ready-to-send provider payloads.
     * Consumed by bin/synthesize-audiobook.php and by any external runner.
     *
     * @param array<string, mixed> $book
     * @param array<string, mixed> $metadata
     * @param array<string, mixed> $options
     * @return array<string, mixed>
     * @throws RuntimeException when cloning is requested without consent.
     */
    public function synthesisManifest(array $book, array $metadata, string $provider = 'google', array $options = []): array
    {
        $provider = in_array($provider, self::PROVIDERS, true) ? $provider : 'google';
        $voice = array_merge($this->defaultVoices()[$provider], is_array($options['voice'] ?? null) ? $options['voice'] : []);
        if ($this->requiresCloneConsent($provider, $voice) && empty($options['voice_consent'])) {
            throw new RuntimeException(
                'Voice cloning from a sampled recording requires the recorded speaker\'s explicit consent. '
                . 'Confirm consent (voice_consent) before generating cloning jobs.'
            );
        }

        $script = $this->narrationScript($book, $metadata);
        $limit = $this->chunkLimit($provider);
        $jobs = [];
        $sections = array_merge(
            [['number' => 0, 'title' => 'Opening credits', 'text' => $script['opening_credits']]],
            $script['chapters'],
            [['number' => count($script['chapters']) + 1, 'title' => 'Closing credits', 'text' => $script['closing_credits']]],
        );
        foreach ($sections as $section) {
            $chunks = $this->chunkText((string) $section['text'], $limit);
            foreach ($chunks as $index => $chunk) {
                $id = sprintf('s%02d-c%03d', (int) $section['number'], $index + 1);
                $jobs[] = [
                    'id' => $id,
                    'section' => (string) $section['title'],
                    'section_number' => (int) $section['number'],
                    'chunk_index' => $index + 1,
                    'chunk_total' => count($chunks),
                    'char_count' => mb_strlen($chunk),
                    'text' => $chunk,
                    'output_file' => $id . ($provider === 'local-clone' ? '.wav' : '.mp3'),
                    'request' => $this->requestPayload($provider, $chunk, $voice),
                ];
            }
        }

        return [
            'version' => 1,
            'provider' => $provider,
            'provider_label' => self::PROVIDER_LABELS[$provider],
            'voice' => $voice,
            'voice_consent' => (bool) ($options['voice_consent'] ?? false),
            'book_title' => (string) ($metadata['title'] ?? 'Untitled'),
            'author' => (string) ($metadata['author'] ?? ''),
            'job_count' => count($jobs),
            'jobs' => $jobs,
        ];
    }

    /**
     * The provider request for one chunk of text.
     *
     * @param array<string, mixed> $voice
     * @return array<string, mixed>
     */
    public function requestPayload(string $provider, string $text, array $voice): array
    {
        if ($provider === 'google') {
            return [
                'endpoint' => 'https://texttospeech.googleapis.com/v1/text:synthesize',
                'method' => 'POST',
                'auth' => 'query parameter key=API_KEY or Authorization: Bearer ACCESS_TOKEN',
                'body' => [
                    'input' => ['text' => $text],
                    'voice' => [
                        'languageCode' => (string) $voice['language_code'],
                        'name' => (string) $voice['voice_name'],
                    ],
                    'audioConfig' => [
                        'audioEncoding' => (string) $voice['audio_encoding'],
                        'speakingRate' => (float) $voice['speaking_rate'],
                        'pitch' => (float) $voice['pitch'],
                    ],
                ],
                'response' => 'JSON with base64 audioContent',
            ];
        }
        if ($provider === 'elevenlabs') {
            return [
                'endpoint' => 'https://api.elevenlabs.io/v1/text-to-speech/' . (string) $voice['voice_id'],
                'method' => 'POST',
                'auth' => 'header xi-api-key: API_KEY',
                'body' => [
                    'text' => $text,
                    'model_id' => (string) $voice['model_id'],
                    'voice_settings' => [
                        'stability' => (float) $voice['stability'],
                        'similarity_boost' => (float) $voice['similarity_boost'],
                    ],
                ],
                'query' => ['output_format' => (string) $voice['output_format']],
                'response' => 'binary audio stream',
            ];
        }
        return [
            'engine' => (string) $voice['engine'],
            'command_template' => 'ENGINE --text {text} --speaker_wav {sample} --language {language} --out {out}',
            'parameters' => [
                'text' => $text,
                'sample' => (string) $voice['sample_path'],
                'language' => (string) $voice['language'],
            ],
            'note' => 'Runs on your own hardware; the sampled speaker must have consented to cloning.',
        ];
    }

    /**
     * ElevenLabs voice-cloning setup request (one-time, before synthesis).
     * Only produced with confirmed consent.
     *
     * @param array<int, string> $samplePaths
     * @return array<string, mixed>
     * @throws RuntimeException without consent.
     */
    public function elevenLabsCloneRequest(string $voiceName, array $samplePaths, bool $voiceConsent): array
    {
        if (!$voiceConsent) {
            throw new RuntimeException(
                'Voice cloning from a sampled recording requires the recorded speaker\'s explicit consent.'
            );
        }
        return [
            'endpoint' => 'https://api.elevenlabs.io/v1/voices/add',
            'method' => 'POST (multipart/form-data)',
            'auth' => 'header xi-api-key: API_KEY',
            'fields' => [
                'name' => $voiceName,
                'files' => array_values($samplePaths),
                'description' => 'Cloned narration voice; recorded speaker consented to cloning.',
            ],
            'sample_guidance' => 'Use 1–3 clean recordings, 1–5 minutes total, single speaker, no music or noise.',
            'response' => 'JSON with the new voice_id — use it as voice.voice_id for synthesis.',
        ];
    }

    /** Plain-text narration script suitable for a narrator or review pass. */
    public function narrationScriptText(array $script): string
    {
        $out = "OPENING CREDITS\n\n" . $script['opening_credits'] . "\n\n";
        foreach ($script['chapters'] as $chapter) {
            $out .= str_repeat('-', 60) . "\n";
            $out .= 'SECTION ' . $chapter['number'] . ' · ' . $chapter['title'] . ' · ' . number_format($chapter['word_count']) . " words\n\n";
            $out .= $chapter['text'] . "\n\n";
        }
        $out .= str_repeat('-', 60) . "\nCLOSING CREDITS\n\n" . $script['closing_credits'] . "\n";
        return $out;
    }

    private function narrationTextForChapter(array $chapter): string
    {
        $text = (string) ($chapter['content'] ?? '');
        // Read job-card labels as spoken sentences rather than list fragments.
        $text = preg_replace('/^(What you do|Who it suits|Where to find it|How to start|Skills and training|Schedule|Safety and age rules):\s*/m', '$1: ', $text) ?? $text;
        // Collapse the visual blank-line rhythm into single paragraph breaks.
        $text = preg_replace('/\R{2,}/u', "\n\n", trim($text)) ?? $text;
        return $text;
    }

    private function chunkLimit(string $provider): int
    {
        return match ($provider) {
            'elevenlabs' => self::ELEVENLABS_MAX_CHUNK_CHARS,
            'local-clone' => self::LOCAL_CLONE_MAX_CHUNK_CHARS,
            default => self::GOOGLE_MAX_CHUNK_CHARS,
        };
    }

    /**
     * Audible-style retail band by finished runtime.
     *
     * @return array{band:string, suggested_price:float, royalty_note:string}
     */
    private function suggestedRetail(float $runtimeHours): array
    {
        [$band, $price] = match (true) {
            $runtimeHours < 1.0 => ['Under 1 hour', 3.95],
            $runtimeHours < 3.0 => ['1–3 hours', 9.95],
            $runtimeHours < 5.0 => ['3–5 hours', 16.95],
            $runtimeHours < 10.0 => ['5–10 hours', 21.95],
            default => ['10–20 hours', 27.95],
        };
        return [
            'band' => $band,
            'suggested_price' => $price,
            'royalty_note' => 'Audible via ACX pays roughly 40% (exclusive) or 25% (non-exclusive) of retail; Amazon sets the final audiobook price.',
        ];
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
}
