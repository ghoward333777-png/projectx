<?php

declare(strict_types=1);

require_once __DIR__ . '/BookIntelligenceEngine.php';
require_once __DIR__ . '/AudiobookProducer.php';
require_once __DIR__ . '/IllustrationStudio.php';
require_once __DIR__ . '/ManuscriptDeveloper.php';

/**
 * Amazon Book Writer
 *
 * Turns a Book Intelligence Studio manuscript into an Amazon KDP-ready
 * publishing package: listing metadata (title, subtitle, description,
 * seven keywords, category suggestions), paperback printing and royalty
 * estimates, an ebook pricing model, a step-by-step publishing checklist,
 * and downloadable manuscript/metadata exports.
 *
 * Like the engine it builds on, it is deterministic and dependency-free.
 * All prices and royalties are directional planning estimates based on
 * published KDP rate cards, not quotes from Amazon.
 */
final class AmazonBookWriter
{
    public const MAX_TITLE_LENGTH = 200;
    public const MAX_DESCRIPTION_LENGTH = 4000;
    public const KEYWORD_SLOTS = 7;
    public const MAX_KEYWORD_LENGTH = 50;

    private const PAPERBACK_MIN_PAGES = 24;
    private const PAPERBACK_MAX_PAGES = 828;
    private const PAPERBACK_ROYALTY_RATE = 0.60;
    private const HARDCOVER_MIN_PAGES = 75;
    private const HARDCOVER_MAX_PAGES = 550;
    private const HARDCOVER_ROYALTY_RATE = 0.60;
    private const EBOOK_ROYALTY_HIGH = 0.70;
    private const EBOOK_ROYALTY_LOW = 0.35;
    private const EBOOK_70_MIN_PRICE = 2.99;
    private const EBOOK_70_MAX_PRICE = 9.99;
    private const EBOOK_DELIVERY_FEE_PER_MB = 0.15;

    private BookIntelligenceEngine $engine;
    private AudiobookProducer $audiobook;

    public function __construct(?BookIntelligenceEngine $engine = null, ?AudiobookProducer $audiobook = null)
    {
        $this->engine = $engine ?? new BookIntelligenceEngine();
        $this->audiobook = $audiobook ?? new AudiobookProducer();
    }

    public function engine(): BookIntelligenceEngine
    {
        return $this->engine;
    }

    public function audiobookProducer(): AudiobookProducer
    {
        return $this->audiobook;
    }

    public function illustrationStudio(): IllustrationStudio
    {
        return $this->illustrations ??= new IllustrationStudio();
    }

    public function manuscriptDeveloper(): ManuscriptDeveloper
    {
        return $this->developer ??= new ManuscriptDeveloper();
    }

    private ?IllustrationStudio $illustrations = null;

    private ?ManuscriptDeveloper $developer = null;

    /**
     * Parse a hand-written table of contents into editable chapter rows.
     *
     * One chapter per line. Leading numbering ("1.", "2)", "Chapter 3:") is
     * stripped, and a line may add its own purpose and detail with pipes:
     * "Title | purpose | detail".
     *
     * @return array<int, array{title:string, purpose:string, detail:string}>
     */
    public static function parseOutline(string $outline): array
    {
        $chapters = [];
        foreach (preg_split('/\R+/u', $outline) ?: [] as $line) {
            $line = trim($line);
            $line = trim((string) preg_replace('/^(?:chapter\s+\d+\s*[:.\-)]?|\d+\s*[:.\-)])\s*/i', '', $line));
            if ($line === '') {
                continue;
            }
            $columns = array_map('trim', explode('|', $line, 3));
            $chapters[] = [
                'title' => $columns[0],
                'purpose' => ($columns[1] ?? '') !== '' ? $columns[1] : 'Advance the book\'s argument with this chapter\'s own story',
                'detail' => ($columns[2] ?? '') !== '' ? $columns[2] : 'Document the current state of this part of the story, contrast it with how things used to be, deconstruct the causes with concrete examples, support the account with evidence, and close with what the reader should take from it.',
            ];
        }
        return $chapters;
    }

    /**
     * Run the full pipeline: strategy kit, manuscript draft, and KDP package.
     *
     * @param array<string, mixed> $options Supports: reader, author, style,
     *   length (preset or page target), chapters (editable TOC rows),
     *   page_style, list_price (paperback), ebook_price.
     * @return array{kit:array<string, mixed>, book:array<string, mixed>, kdp:array<string, mixed>}
     */
    public function writeBook(string $topic, array $options = []): array
    {
        $reader = trim((string) ($options['reader'] ?? ''));
        $kit = $this->engine->buildKit($topic, ['reader' => $reader]);
        $chapters = is_array($options['chapters'] ?? null) && $options['chapters'] !== []
            ? $options['chapters']
            : $kit['blueprint']['chapters'];

        $book = $this->engine->generateBookFromTableOfContents(
            $topic,
            $chapters,
            (string) ($options['style'] ?? 'conversational'),
            $options['length'] ?? 'standard',
            $reader,
            (string) ($kit['blueprint']['positioning']['core_promise'] ?? ''),
            is_array($options['page_style'] ?? null) ? $options['page_style'] : [],
        );

        // The voice contract travels with the book so every AI drafting pass
        // holds it exactly — narrative person, perspective factors, and the
        // author's own voice description.
        $narrative = (string) ($options['narrative_voice'] ?? '');
        $book['voice'] = [
            'narrative' => isset(ManuscriptDeveloper::NARRATIVE_VOICES[$narrative]) ? $narrative : 'third-person',
            'perspectives' => array_values(array_filter(
                array_map('strval', (array) ($options['perspectives'] ?? [])),
                static fn (string $factor): bool => isset(ManuscriptDeveloper::PERSPECTIVE_FACTORS[$factor]),
            )),
            'author_voice' => trim((string) ($options['author_voice'] ?? '')),
        ];

        // Developed prose (from the AI Manuscript Developer or pasted by the
        // author) replaces the engine's draft directions chapter by chapter.
        if (is_array($options['developed_chapters'] ?? null) && $options['developed_chapters'] !== []) {
            $book = $this->manuscriptDeveloper()->applyDevelopedChapters($book, $options['developed_chapters']);
        }

        $kdp = $this->buildKdpPackage($topic, $kit, $book, $options);

        return [
            'kit' => $kit,
            'book' => $book,
            'kdp' => $kdp,
            'outline_review' => $this->engine->reviewOutline($topic, $chapters),
            'media' => $this->illustrationStudio()->planBookMedia(
                $book,
                $kdp['metadata'],
                is_array($options['extra_media'] ?? null) ? $options['extra_media'] : [],
            ),
        ];
    }

    /**
     * Assemble the Amazon KDP publishing package for an already generated book.
     *
     * @param array<string, mixed> $kit
     * @param array<string, mixed> $book
     * @param array<string, mixed> $options
     * @return array<string, mixed>
     */
    public function buildKdpPackage(string $topic, array $kit, array $book, array $options = []): array
    {
        $author = trim((string) ($options['author'] ?? '')) ?: 'Independent Author';
        $metadata = $this->listingMetadata($topic, $kit, $book, $author);
        $manuscriptPlan = $this->manuscriptPlan($book);
        $paperback = $this->paperbackPlan(
            (int) $manuscriptPlan['kdp_page_estimate'],
            isset($options['list_price']) ? (float) $options['list_price'] : null,
        );
        $ebook = $this->ebookPlan(
            (int) ($book['total_word_count'] ?? 0),
            isset($options['ebook_price']) ? (float) $options['ebook_price'] : null,
        );
        $hardcover = $this->hardcoverPlan(
            (int) $manuscriptPlan['kdp_page_estimate'],
            isset($options['hardcover_price']) ? (float) $options['hardcover_price'] : null,
        );
        $audiobookProvider = in_array($options['audiobook_provider'] ?? '', AudiobookProducer::PROVIDERS, true)
            ? (string) $options['audiobook_provider']
            : 'google';
        $audiobookPlan = $this->audiobook->plan($book, $metadata, $audiobookProvider, [
            'voice' => is_array($options['audiobook_voice'] ?? null) ? $options['audiobook_voice'] : [],
            'voice_consent' => (bool) ($options['voice_consent'] ?? false),
        ]);

        return [
            'marketplace' => 'Amazon.com (KDP)',
            'currency' => 'USD',
            'disclaimer' => 'Printing costs, royalties, and category names are directional estimates from published KDP rate cards. Confirm live numbers inside KDP before publishing.',
            'metadata' => $metadata,
            'manuscript' => $manuscriptPlan,
            'paperback' => $paperback,
            'ebook' => $ebook,
            'editions' => [
                'kindle' => [
                    'label' => 'Kindle eBook',
                    'channel' => 'KDP · Kindle Store',
                    'price' => $ebook['price'],
                    'royalty_per_copy' => $ebook['royalty_per_copy'],
                    'royalty_plan' => $ebook['royalty_plan'],
                    'deliverable' => 'Manuscript HTML export (imports into Kindle Create; export as KPF or EPUB)',
                ],
                'paperback' => [
                    'label' => 'Paperback',
                    'channel' => 'KDP Print · ' . $manuscriptPlan['trim_size'],
                    'price' => $paperback['list_price'],
                    'royalty_per_copy' => $paperback['royalty_per_copy'],
                    'royalty_plan' => '60% of list − printing cost',
                    'deliverable' => 'Interior PDF at ' . $manuscriptPlan['trim_size'] . ' + cover at spine width for ' . $paperback['page_count'] . ' pages',
                ],
                'hardcover' => [
                    'label' => 'Hardcover',
                    'channel' => 'KDP Print · case laminate · ' . $manuscriptPlan['trim_size'],
                    'price' => $hardcover['list_price'],
                    'royalty_per_copy' => $hardcover['royalty_per_copy'],
                    'royalty_plan' => '60% of list − printing cost',
                    'deliverable' => 'Same interior PDF + hardcover case wrap for ' . $hardcover['page_count'] . ' pages',
                ],
                'audiobook' => [
                    'label' => 'Audiobook',
                    'channel' => 'Audible via ACX / KDP Virtual Voice',
                    'price' => $audiobookPlan['suggested_retail']['suggested_price'],
                    'royalty_per_copy' => round($audiobookPlan['suggested_retail']['suggested_price'] * 0.40, 2),
                    'royalty_plan' => '≈40% exclusive / 25% non-exclusive of Audible retail',
                    'deliverable' => number_format($audiobookPlan['runtime_estimate_hours'], 1) . ' finished hours · ' . $audiobookPlan['provider_label'],
                ],
            ],
            'hardcover' => $hardcover,
            'audiobook' => $audiobookPlan,
            'checklist' => $this->publishingChecklist($metadata, $manuscriptPlan, $paperback, $ebook, $hardcover, $audiobookPlan),
        ];
    }

    /**
     * Hardcover printing cost and royalty model (US marketplace, B&W interior,
     * case laminate). KDP hardcovers run 75–550 pages.
     *
     * @return array<string, mixed>
     */
    public function hardcoverPlan(int $pageCount, ?float $listPrice = null): array
    {
        $pageCount = max(self::HARDCOVER_MIN_PAGES, min(self::HARDCOVER_MAX_PAGES, $pageCount));
        $printingCost = $pageCount <= 108
            ? 6.80
            : 5.65 + ($pageCount * 0.012);
        $printingCost = round($printingCost, 2);
        $minListPrice = $this->roundUpTo99($printingCost / self::HARDCOVER_ROYALTY_RATE);
        $suggestedListPrice = $this->roundUpTo99(max($minListPrice, min(34.99, 14.99 + ($pageCount * 0.02))));
        $listPrice = $listPrice !== null ? round(max($minListPrice, $listPrice), 2) : $suggestedListPrice;
        $royalty = round((self::HARDCOVER_ROYALTY_RATE * $listPrice) - $printingCost, 2);

        return [
            'page_count' => $pageCount,
            'printing_cost' => $printingCost,
            'royalty_rate' => self::HARDCOVER_ROYALTY_RATE,
            'minimum_list_price' => $minListPrice,
            'suggested_list_price' => $suggestedListPrice,
            'list_price' => $listPrice,
            'royalty_per_copy' => max(0.0, $royalty),
            'formula' => 'royalty = (60% × list price) − printing cost',
        ];
    }

    /**
     * Build the Amazon listing fields with KDP limits enforced.
     *
     * @param array<string, mixed> $kit
     * @param array<string, mixed> $book
     * @return array<string, mixed>
     */
    public function listingMetadata(string $topic, array $kit, array $book, string $author): array
    {
        $topicLabel = ucwords(strtolower(trim($topic)));
        $workingTitle = (string) ($kit['blueprint']['positioning']['working_title'] ?? $topicLabel);
        [$title, $subtitle] = $this->splitTitle($workingTitle, $topicLabel);

        return [
            'title' => $title,
            'subtitle' => $subtitle,
            'author' => $author,
            'language' => 'English',
            'description' => $this->listingDescription($topicLabel, $kit, $book),
            'keywords' => $this->listingKeywords($topic, $kit),
            'categories' => $this->categorySuggestions($topic),
            'limits' => [
                'title_max_chars' => self::MAX_TITLE_LENGTH,
                'description_max_chars' => self::MAX_DESCRIPTION_LENGTH,
                'keyword_slots' => self::KEYWORD_SLOTS,
                'keyword_max_chars' => self::MAX_KEYWORD_LENGTH,
            ],
        ];
    }

    /**
     * Compose the KDP book description within the 4,000 character limit.
     *
     * @param array<string, mixed> $kit
     * @param array<string, mixed> $book
     */
    public function listingDescription(string $topicLabel, array $kit, array $book): string
    {
        $persona = (string) ($kit['topic_analysis']['reader_persona']['primary'] ?? 'curious readers');
        $job = (string) ($kit['topic_analysis']['reader_persona']['job_to_be_done'] ?? 'understand the topic and make a better decision');
        $angle = (string) ($kit['blueprint']['positioning']['core_promise'] ?? 'a practical path through the topic');
        $opportunity = (string) ($kit['competition']['opportunities'][0] ?? 'Connect evidence to action.');

        $paragraphs = [
            strtoupper($topicLabel) . ', MADE USABLE.',
            'This book was written for ' . strtolower($persona) . ' who want to ' . strtolower($job)
                . ' Its promise is simple: ' . strtolower($angle) . '.',
            'Instead of another information dump, every chapter pairs context with a next move: '
                . strtolower($opportunity),
        ];

        $chapterLines = ['Inside, you will find:'];
        foreach (array_slice((array) ($book['table_of_contents'] ?? []), 0, 10) as $entry) {
            $chapterLines[] = '- ' . (string) ($entry['title'] ?? '');
        }
        $tocCount = count((array) ($book['table_of_contents'] ?? []));
        if ($tocCount > 10) {
            $chapterLines[] = '...and ' . ($tocCount - 10) . ' more chapters of guided, practical material.';
        }
        $paragraphs[] = implode("\n", $chapterLines);
        $paragraphs[] = 'Each chapter ends with a concrete action, so the book keeps working after you close it. '
            . 'If you want a guide that respects your time and turns understanding into progress, start reading today.';

        $description = implode("\n\n", $paragraphs);
        if (mb_strlen($description) > self::MAX_DESCRIPTION_LENGTH) {
            $description = rtrim(mb_substr($description, 0, self::MAX_DESCRIPTION_LENGTH - 1)) . '…';
        }
        return $description;
    }

    /**
     * Produce exactly seven backend search keywords, each within 50 characters.
     *
     * @param array<string, mixed> $kit
     * @return array<int, string>
     */
    public function listingKeywords(string $topic, array $kit): array
    {
        $topicLower = strtolower(trim(preg_replace('/\s+/', ' ', $topic) ?? ''));
        $persona = strtolower((string) ($kit['topic_analysis']['reader_persona']['primary'] ?? 'readers'));
        $candidates = [
            $topicLower . ' guide',
            $topicLower . ' book',
            'how to ' . $topicLower,
            $topicLower . ' for beginners',
            $topicLower . ' explained',
            'practical ' . $topicLower,
            $topicLower . ' for ' . $persona,
            $topicLower . ' handbook',
            $topicLower . ' step by step',
            'learn ' . $topicLower,
        ];

        $keywords = [];
        foreach ($candidates as $candidate) {
            $candidate = trim(preg_replace('/\s+/', ' ', $candidate) ?? '');
            if ($candidate === '' || mb_strlen($candidate) > self::MAX_KEYWORD_LENGTH) {
                continue;
            }
            if (!in_array($candidate, $keywords, true)) {
                $keywords[] = $candidate;
            }
            if (count($keywords) === self::KEYWORD_SLOTS) {
                break;
            }
        }
        while (count($keywords) < self::KEYWORD_SLOTS) {
            $filler = mb_substr($topicLower . ' ' . (count($keywords) + 1), 0, self::MAX_KEYWORD_LENGTH);
            $keywords[] = $filler;
        }
        return $keywords;
    }

    /**
     * Suggest up to three Amazon browse categories from topic signals.
     *
     * @return array<int, string>
     */
    public function categorySuggestions(string $topic): array
    {
        $normalized = strtolower($topic);
        $isTeen = preg_match('/teen|teenager|youth|student|high school|young people/', $normalized) === 1;
        $map = [
            '/job|work|career|employment|resume|interview/' => $isTeen
                ? ['Teen & Young Adult > Education & Reference > Careers', 'Business & Money > Job Hunting & Careers > Job Hunting', 'Education & Teaching > Studying & Workbooks']
                : ['Business & Money > Job Hunting & Careers', 'Self-Help > Motivational', 'Business & Money > Skills'],
            '/money|finance|invest|budget|saving/' => ['Business & Money > Personal Finance', 'Self-Help > Personal Transformation', 'Business & Money > Investing'],
            '/ai|software|programming|technology|computer|data/' => ['Computers & Technology', 'Science & Math > Technology', 'Business & Money > Industries > Computers & Technology'],
            '/health|wellness|fitness|diet|mindful/' => ['Health, Fitness & Dieting', 'Self-Help > Stress Management', 'Health, Fitness & Dieting > Mental Health'],
            '/history|war|biography/' => ['History', 'Biographies & Memoirs', 'Education & Teaching'],
            '/leadership|management|business|startup|marketing/' => ['Business & Money > Management & Leadership', 'Business & Money > Marketing & Sales', 'Business & Money > Entrepreneurship'],
            '/writing|craft|design|art|creative/' => ['Reference > Writing, Research & Publishing Guides', 'Arts & Photography', 'Self-Help > Creativity'],
        ];
        foreach ($map as $pattern => $categories) {
            if (preg_match($pattern, $normalized) === 1) {
                return $categories;
            }
        }
        return ['Reference', 'Self-Help > Personal Transformation', 'Education & Teaching'];
    }

    /**
     * Interior plan: trim size and a KDP-oriented page estimate.
     *
     * @param array<string, mixed> $book
     * @return array<string, mixed>
     */
    public function manuscriptPlan(array $book): array
    {
        $draftPages = (int) ($book['page_count'] ?? 0);
        $frontBackMatterPages = 6; // title, copyright, dedication, TOC spread, about the author
        $kdpPages = max(self::PAPERBACK_MIN_PAGES, min(self::PAPERBACK_MAX_PAGES, $draftPages + $frontBackMatterPages));

        return [
            'trim_size' => '6 x 9 in (15.24 x 22.86 cm)',
            'interior' => 'Black & white interior on white paper',
            'bleed' => 'No bleed',
            'draft_page_count' => $draftPages,
            'front_back_matter_pages' => $frontBackMatterPages,
            'kdp_page_estimate' => $kdpPages,
            'page_count_notes' => $draftPages + $frontBackMatterPages < self::PAPERBACK_MIN_PAGES
                ? 'KDP paperbacks require at least ' . self::PAPERBACK_MIN_PAGES . ' pages; the interior will be padded to the minimum.'
                : ($draftPages + $frontBackMatterPages > self::PAPERBACK_MAX_PAGES
                    ? 'KDP black & white paperbacks max out at ' . self::PAPERBACK_MAX_PAGES . ' pages; split the manuscript or tighten chapters.'
                    : 'Page count fits KDP black & white paperback limits.'),
            'total_word_count' => (int) ($book['total_word_count'] ?? 0),
            'front_matter' => ['Title page', 'Copyright page', 'Table of contents'],
            'back_matter' => ['About the author', 'Review request page'],
        ];
    }

    /**
     * Paperback printing cost and royalty model (US marketplace, B&W interior).
     *
     * @return array<string, mixed>
     */
    public function paperbackPlan(int $pageCount, ?float $listPrice = null): array
    {
        $pageCount = max(self::PAPERBACK_MIN_PAGES, min(self::PAPERBACK_MAX_PAGES, $pageCount));
        $printingCost = $pageCount <= 108
            ? 2.30
            : 1.00 + ($pageCount * 0.012);
        $printingCost = round($printingCost, 2);
        $minListPrice = $this->roundUpTo99($printingCost / self::PAPERBACK_ROYALTY_RATE);
        $suggestedListPrice = $this->roundUpTo99(max($minListPrice, min(24.99, 7.99 + ($pageCount * 0.02))));
        $listPrice = $listPrice !== null ? round(max($minListPrice, $listPrice), 2) : $suggestedListPrice;
        $royalty = round((self::PAPERBACK_ROYALTY_RATE * $listPrice) - $printingCost, 2);

        return [
            'page_count' => $pageCount,
            'printing_cost' => $printingCost,
            'royalty_rate' => self::PAPERBACK_ROYALTY_RATE,
            'minimum_list_price' => $minListPrice,
            'suggested_list_price' => $suggestedListPrice,
            'list_price' => $listPrice,
            'royalty_per_copy' => max(0.0, $royalty),
            'formula' => 'royalty = (60% × list price) − printing cost',
        ];
    }

    /**
     * Kindle ebook pricing and royalty model.
     *
     * @return array<string, mixed>
     */
    public function ebookPlan(int $totalWordCount, ?float $price = null): array
    {
        $fileSizeMb = max(0.5, round($totalWordCount / 175000, 2)); // plain-text manuscripts stay small
        $deliveryFee = round($fileSizeMb * self::EBOOK_DELIVERY_FEE_PER_MB, 2);
        $suggestedPrice = $totalWordCount >= 60000 ? 6.99 : ($totalWordCount >= 25000 ? 4.99 : self::EBOOK_70_MIN_PRICE);
        $price = $price !== null ? round($price, 2) : $suggestedPrice;
        $qualifiesFor70 = $price >= self::EBOOK_70_MIN_PRICE && $price <= self::EBOOK_70_MAX_PRICE;
        $royaltyRate = $qualifiesFor70 ? self::EBOOK_ROYALTY_HIGH : self::EBOOK_ROYALTY_LOW;
        $royalty = $qualifiesFor70
            ? round(($price - $deliveryFee) * $royaltyRate, 2)
            : round($price * $royaltyRate, 2);

        return [
            'suggested_price' => $suggestedPrice,
            'price' => $price,
            'royalty_plan' => $qualifiesFor70 ? '70% (price within $2.99–$9.99)' : '35% (price outside $2.99–$9.99)',
            'royalty_rate' => $royaltyRate,
            'estimated_file_size_mb' => $fileSizeMb,
            'delivery_fee' => $qualifiesFor70 ? $deliveryFee : 0.0,
            'royalty_per_copy' => max(0.0, $royalty),
            'formula' => $qualifiesFor70
                ? 'royalty = 70% × (price − delivery fee)'
                : 'royalty = 35% × price',
        ];
    }

    /**
     * Ordered publishing checklist reflecting the current package state.
     *
     * @param array<string, mixed> $metadata
     * @param array<string, mixed> $manuscript
     * @param array<string, mixed> $paperback
     * @param array<string, mixed> $ebook
     * @return array<int, array{step:string, status:string, detail:string}>
     */
    public function publishingChecklist(
        array $metadata,
        array $manuscript,
        array $paperback,
        array $ebook,
        array $hardcover = [],
        array $audiobook = [],
    ): array {
        $extra = [];
        if ($hardcover !== []) {
            $extra[] = ['step' => 'Hardcover edition', 'status' => 'Ready', 'detail' => 'Case-laminate hardcover at $' . number_format((float) $hardcover['list_price'], 2) . ' (≈ $' . number_format((float) $hardcover['royalty_per_copy'], 2) . '/copy, printing $' . number_format((float) $hardcover['printing_cost'], 2) . '). Enable it as a second format on the same KDP title.'];
        }
        if ($audiobook !== []) {
            $consentBlocked = ($audiobook['clone_consent']['required'] ?? false) && !($audiobook['clone_consent']['confirmed'] ?? false);
            $extra[] = [
                'step' => 'Audiobook production',
                'status' => $consentBlocked ? 'Action needed' : 'Ready',
                'detail' => number_format((float) $audiobook['runtime_estimate_hours'], 1) . ' finished hours via ' . $audiobook['provider_label']
                    . ' · est. synthesis cost $' . number_format((float) $audiobook['estimated_synthesis_cost_usd'], 2)
                    . '. ' . ($consentBlocked
                        ? 'Blocked until the sampled speaker\'s cloning consent is confirmed.'
                        : 'Generate the manifest, run bin/synthesize-audiobook.php, master to ACX specs.'),
            ];
        }
        return array_merge([
            ['step' => 'Draft manuscript', 'status' => 'Ready', 'detail' => number_format((int) $manuscript['total_word_count']) . ' words across ' . number_format((int) $manuscript['draft_page_count']) . ' draft pages. Review voice, claims, and examples before upload.'],
            ['step' => 'Listing metadata', 'status' => 'Ready', 'detail' => 'Title, subtitle, description, ' . count((array) $metadata['keywords']) . ' keywords, and ' . count((array) $metadata['categories']) . ' category suggestions generated within KDP limits.'],
            ['step' => 'Interior formatting', 'status' => 'Action needed', 'detail' => 'Export the manuscript file below, open it in Kindle Create or Word, and confirm ' . (string) $manuscript['trim_size'] . ' with mirrored margins.'],
            ['step' => 'Cover design', 'status' => 'Action needed', 'detail' => 'Create a cover at the KDP-calculated spine width for ' . number_format((int) $paperback['page_count']) . ' pages, or use KDP Cover Creator.'],
            ['step' => 'Pricing', 'status' => 'Ready', 'detail' => 'Paperback $' . number_format((float) $paperback['list_price'], 2) . ' (≈ $' . number_format((float) $paperback['royalty_per_copy'], 2) . '/copy) · Kindle $' . number_format((float) $ebook['price'], 2) . ' (≈ $' . number_format((float) $ebook['royalty_per_copy'], 2) . '/copy).'],
            ['step' => 'Rights & tax interview', 'status' => 'Action needed', 'detail' => 'Confirm you hold worldwide rights and complete the KDP tax interview before the first upload.'],
            ['step' => 'Publish & review proof', 'status' => 'Pending', 'detail' => 'Order a printed proof, check the physical copy, then press Publish. Amazon review typically takes up to 72 hours.'],
        ], $extra);
    }

    /**
     * Render a KDP-ready single-file HTML manuscript (imports cleanly into
     * Kindle Create and Word) with title page, copyright, TOC, and chapters.
     *
     * @param array<string, mixed> $book
     * @param array<string, mixed> $metadata
     */
    /**
     * @param array<string, mixed>|null $media Output of IllustrationStudio::planBookMedia().
     * @param array<string, mixed>|null $companion Output of PrintMediaCompanion::companionPlan();
     *   when given, each chapter ends with its QR code to the companion page.
     */
    public function exportManuscriptHtml(array $book, array $metadata, ?array $media = null, ?array $companion = null): string
    {
        $mediaByChapter = [];
        foreach ((array) ($media['chapters'] ?? []) as $mediaChapter) {
            $mediaByChapter[(int) $mediaChapter['number']] = (array) $mediaChapter['items'];
        }
        $companionByChapter = [];
        foreach ((array) ($companion['chapters'] ?? []) as $entry) {
            $companionByChapter[(int) $entry['chapter']] = $entry;
        }
        $e = static fn (string $value): string => htmlspecialchars($value, ENT_QUOTES, 'UTF-8');
        $title = (string) ($metadata['title'] ?? 'Untitled');
        $subtitle = (string) ($metadata['subtitle'] ?? '');
        $author = (string) ($metadata['author'] ?? 'Independent Author');
        $year = gmdate('Y');

        $html = "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n<title>" . $e($title) . "</title>\n"
            . "<style>\nbody { font-family: \"Times New Roman\", Georgia, serif; font-size: 12pt; line-height: 1.5; margin: 1in; }\n"
            . "h1, h2 { text-align: center; page-break-before: always; }\nh1.title-page { page-break-before: avoid; margin-top: 30%; }\n"
            . ".subtitle, .author { text-align: center; }\n.copyright { page-break-before: always; font-size: 10pt; text-align: center; margin-top: 40%; }\n"
            . "p { text-indent: 1.5em; margin: 0 0 0.4em; }\np.no-indent { text-indent: 0; }\nnav p { text-indent: 0; }\n</style>\n</head>\n<body>\n";

        $html .= '<h1 class="title-page">' . $e($title) . "</h1>\n";
        if ($subtitle !== '') {
            $html .= '<p class="subtitle no-indent"><em>' . $e($subtitle) . "</em></p>\n";
        }
        $html .= '<p class="author no-indent">' . $e($author) . "</p>\n";
        $html .= '<div class="copyright"><p class="no-indent">Copyright © ' . $e($year) . ' ' . $e($author)
            . '. All rights reserved.</p><p class="no-indent">No part of this book may be reproduced in any form without written permission, '
            . 'except for brief quotations in reviews.</p></div>' . "\n";

        $html .= "<h2>Table of Contents</h2>\n<nav>\n";
        foreach ((array) ($book['table_of_contents'] ?? []) as $entry) {
            $number = (int) ($entry['number'] ?? 0);
            $html .= '<p><a href="#chapter-' . $number . '">' . $number . '. ' . $e((string) ($entry['title'] ?? '')) . "</a></p>\n";
        }
        $html .= "</nav>\n";

        foreach ((array) ($book['chapters'] ?? []) as $chapter) {
            $number = (int) ($chapter['number'] ?? 0);
            $html .= '<h2 id="chapter-' . $number . '">Chapter ' . $number . ': ' . $e((string) ($chapter['title'] ?? '')) . "</h2>\n";
            foreach ((array) ($chapter['blocks'] ?? []) as $index => $block) {
                $content = (string) ($block['content'] ?? '');
                if ($content === '' || ($index === 0 && ($block['kind'] ?? '') === 'heading')) {
                    continue; // the chapter heading is already rendered above
                }
                $html .= '<p>' . nl2br($e($content)) . "</p>\n";
            }
            $figureNumber = 0;
            foreach ($mediaByChapter[$number] ?? [] as $item) {
                if (!empty($item['placeholder'])) {
                    continue; // AI images join the manuscript once actually generated
                }
                $figureNumber++;
                $html .= '<figure style="margin: 1.5em 0; page-break-inside: avoid;">' . "\n";
                if (isset($item['svg'])) {
                    $html .= $item['svg'] . "\n"; // studio-generated SVG, already escaped internally
                } elseif (isset($item['table']['columns'], $item['table']['rows'])) {
                    $html .= '<table style="border-collapse: collapse; width: 100%; font-size: 10pt;"><thead><tr>';
                    foreach ($item['table']['columns'] as $column) {
                        $html .= '<th style="border: 1px solid #999; padding: 4pt 6pt; text-align: left;">' . $e((string) $column) . '</th>';
                    }
                    $html .= '</tr></thead><tbody>';
                    foreach ($item['table']['rows'] as $row) {
                        $html .= '<tr>';
                        foreach ($row as $cell) {
                            $html .= '<td style="border: 1px solid #bbb; padding: 4pt 6pt; vertical-align: top;">' . $e((string) $cell) . '</td>';
                        }
                        $html .= '</tr>';
                    }
                    $html .= "</tbody></table>\n";
                }
                $html .= '<figcaption style="font-size: 10pt; text-align: center; font-style: italic;">Figure ' . $number . '.' . $figureNumber . ' — ' . $e((string) ($item['title'] ?? '')) . '. ' . $e((string) ($item['caption'] ?? '')) . '</figcaption>' . "\n</figure>\n";
            }
            if (isset($companionByChapter[$number])) {
                $entry = $companionByChapter[$number];
                $html .= '<figure style="margin: 1.5em 0; text-align: center; page-break-inside: avoid;">' . $entry['qr_svg']
                    . '<figcaption style="font-size: 9pt; font-style: italic;">Scan for this chapter\'s media — audio, images, and figures: '
                    . $e((string) $entry['url']) . '</figcaption></figure>' . "\n";
            }
        }

        $html .= '<h2>About the Author</h2><p class="no-indent">' . $e($author)
            . ' writes practical, reader-first guides. If this book helped you, please consider leaving a review on Amazon — it is the best way to help other readers find it.</p>' . "\n";
        return $html . "</body>\n</html>\n";
    }

    /**
     * Metadata export shaped for copy-paste into the KDP setup screens.
     *
     * @param array<string, mixed> $kdp
     * @return array<string, mixed>
     */
    public function exportMetadata(array $kdp): array
    {
        return [
            'generated_at' => gmdate(DATE_ATOM),
            'marketplace' => $kdp['marketplace'] ?? 'Amazon.com (KDP)',
            'kdp_book_details' => [
                'title' => $kdp['metadata']['title'] ?? '',
                'subtitle' => $kdp['metadata']['subtitle'] ?? '',
                'author' => $kdp['metadata']['author'] ?? '',
                'language' => $kdp['metadata']['language'] ?? 'English',
                'description' => $kdp['metadata']['description'] ?? '',
                'keywords' => $kdp['metadata']['keywords'] ?? [],
                'categories' => $kdp['metadata']['categories'] ?? [],
            ],
            'kdp_print_options' => [
                'trim_size' => $kdp['manuscript']['trim_size'] ?? '',
                'interior' => $kdp['manuscript']['interior'] ?? '',
                'bleed' => $kdp['manuscript']['bleed'] ?? '',
                'page_count_estimate' => $kdp['manuscript']['kdp_page_estimate'] ?? 0,
            ],
            'kdp_pricing' => [
                'paperback' => $kdp['paperback'] ?? [],
                'ebook' => $kdp['ebook'] ?? [],
                'hardcover' => $kdp['hardcover'] ?? [],
            ],
            'editions' => $kdp['editions'] ?? [],
            'audiobook' => $kdp['audiobook'] ?? [],
            'checklist' => $kdp['checklist'] ?? [],
            'disclaimer' => $kdp['disclaimer'] ?? '',
        ];
    }

    /**
     * Split an engine working title into KDP title and subtitle fields,
     * keeping the combined listing title within the 200 character limit.
     *
     * @return array{0:string, 1:string}
     */
    private function splitTitle(string $workingTitle, string $fallback): array
    {
        $workingTitle = trim($workingTitle) ?: $fallback;
        $title = $workingTitle;
        $subtitle = '';
        if (str_contains($workingTitle, ':')) {
            [$title, $subtitle] = array_map('trim', explode(':', $workingTitle, 2));
        }
        if ($title === '') {
            $title = $fallback;
        }
        if (mb_strlen($title) > self::MAX_TITLE_LENGTH) {
            $title = rtrim(mb_substr($title, 0, self::MAX_TITLE_LENGTH - 1)) . '…';
        }
        $subtitleBudget = self::MAX_TITLE_LENGTH - mb_strlen($title);
        if (mb_strlen($subtitle) > $subtitleBudget) {
            $subtitle = $subtitleBudget > 1 ? rtrim(mb_substr($subtitle, 0, $subtitleBudget - 1)) . '…' : '';
        }
        return [$title, $subtitle];
    }

    private function roundUpTo99(float $value): float
    {
        $whole = floor($value);
        $candidate = $whole + 0.99;
        if ($candidate < $value) {
            $candidate += 1.0;
        }
        return round($candidate, 2);
    }
}
