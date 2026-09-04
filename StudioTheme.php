<?php

declare(strict_types=1);

/**
 * The studio shell shared by every page: the dark rail with the studio steps,
 * the sticky workspace header, the progress strip, and the paper-and-coral
 * design system ported from the original Book Intelligence Studio interface.
 *
 * Usage:
 *   StudioTheme::head('Book generator');           // inside <head>
 *   StudioTheme::open(['active' => 'writer', ...]) // right after <body>
 *   ... page content (rendered inside .studio-content) ...
 *   StudioTheme::close();                          // before </body>
 */
final class StudioTheme
{
    /** @var array<string, array{href: string, index: string, label: string, descriptor: string, icon: string}> */
    public const STEPS = [
        'topic' => ['href' => 'index.php#topic', 'index' => '01', 'label' => 'Topic', 'descriptor' => 'Find the signal', 'icon' => 'target'],
        'scan' => ['href' => 'index.php#scan', 'index' => '02', 'label' => 'Competitive scan', 'descriptor' => 'See the field', 'icon' => 'search'],
        'blueprint' => ['href' => 'index.php#blueprint', 'index' => '03', 'label' => 'Blueprint', 'descriptor' => 'Shape the argument', 'icon' => 'layers'],
        'media' => ['href' => 'index.php#media', 'index' => '04', 'label' => 'Media plan', 'descriptor' => 'Build the flywheel', 'icon' => 'video'],
        'probability' => ['href' => 'index.php#probability', 'index' => '05', 'label' => 'Probability', 'descriptor' => 'Make the bet', 'icon' => 'gauge'],
    ];

    public static function head(string $title): void
    {
        echo '<meta charset="utf-8">' . "\n";
        echo '<meta name="viewport" content="width=device-width, initial-scale=1">' . "\n";
        echo '<title>' . htmlspecialchars($title, ENT_QUOTES, 'UTF-8') . ' · Book Intelligence Studio</title>' . "\n";
        echo '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>' . "\n";
        echo '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600;700&family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600;6..72,700&display=swap">' . "\n";
        echo '<style>' . self::css() . '</style>' . "\n";
    }

    /**
     * Open the studio shell. Options:
     *  - active: topic|scan|blueprint|media|probability|kit|writer|advanced|lab|library|guide
     *  - current: header breadcrumb label (defaults from active)
     *  - brief: the current brief/topic title for the rail
     *  - progress_label / progress_value / progress_percent: the strip under the header
     *  - library_count: saved projects count
     *  - steps_complete: whether the five studio steps show as complete
     */
    public static function open(array $options = []): void
    {
        $active = (string) ($options['active'] ?? 'topic');
        if (session_status() === PHP_SESSION_NONE && !headers_sent()) {
            session_start();
        }
        $brief = trim((string) ($options['brief'] ?? ''));
        if ($brief === '') {
            $brief = trim((string) ($_SESSION['book_topic'] ?? ''));
        }
        if ($brief === '') {
            $brief = 'Untitled book brief';
        }
        $libraryCount = (int) ($options['library_count'] ?? self::projectCount());
        $stepsComplete = (bool) ($options['steps_complete'] ?? true);
        $currentDefaults = [
            'kit' => 'Complete kit', 'writer' => 'Book generator', 'advanced' => 'Amazon packaging',
            'lab' => 'Quality lab', 'library' => 'Library', 'guide' => 'User guide',
        ];
        $current = (string) ($options['current'] ?? $currentDefaults[$active] ?? (self::STEPS[$active]['label'] ?? 'Workspace'));
        $progressLabel = (string) ($options['progress_label'] ?? 'Strategy kit ready');
        $progressValue = (string) ($options['progress_value'] ?? '100% mapped');
        $progressPercent = max(0, min(100, (int) ($options['progress_percent'] ?? 100)));
        $h = static fn (string $v): string => htmlspecialchars($v, ENT_QUOTES, 'UTF-8');

        echo '<div class="noise studio-shell">';
        echo '<aside class="studio-rail">';
        echo '<a class="rail-brand" href="index.php"><span class="brand-mark">' . self::icon('book', 18) . '</span><span><span class="rail-brand-name">Book Intelligence</span><span class="rail-brand-sub">Studio <span>•</span> local workspace</span></span></a>';
        echo '<div class="rail-project"><div class="rail-project-label">CURRENT BRIEF</div><div class="rail-project-title">' . $h($brief) . '</div><div class="rail-project-status"><span class="status-dot"></span> Saved on this device</div></div>';
        echo '<a class="rail-library-link rail-library-link-prominent' . ($active === 'library' ? ' active' : '') . '" href="book-projects.php">' . self::icon('archive', 17) . '<span>Library</span><span class="kit-count">' . $libraryCount . '</span></a>';
        echo '<nav class="rail-nav" aria-label="Studio steps"><div class="rail-nav-label">THE STUDIO</div>';
        foreach (self::STEPS as $id => $step) {
            $classes = 'rail-step' . ($active === $id ? ' active' : '') . ($stepsComplete ? ' complete' : '');
            $icon = $stepsComplete && $active !== $id ? self::icon('check', 15) : self::icon($step['icon'], 17);
            echo '<a class="' . $classes . '" href="' . $h($step['href']) . '"><span class="rail-step-icon">' . $icon . '</span><span class="rail-step-text"><b>' . $h($step['label']) . '</b><small>' . $h($step['descriptor']) . '</small></span><span class="rail-step-index">' . $step['index'] . '</span></a>';
        }
        echo '<a class="rail-kit-link' . ($active === 'kit' ? ' active' : '') . '" href="index.php#kit">' . self::icon('clipboard', 17) . '<span>Complete kit</span><span class="kit-count">5/5</span></a>';
        echo '<a class="rail-writer-link' . ($active === 'writer' ? ' active' : '') . '" href="generate-book.php">' . self::icon('pen', 17) . '<span>Book generator</span><span class="kit-count">' . ($active === 'writer' ? 'DRAFT' : 'OPEN') . '</span></a>';
        echo '<a class="rail-library-link' . ($active === 'advanced' ? ' active' : '') . '" href="amazon-book-writer.php">' . self::icon('sparkles', 17) . '<span>Amazon packaging</span><span class="kit-count">KDP</span></a>';
        echo '<a class="rail-library-link' . ($active === 'lab' ? ' active' : '') . '" href="book-lab.php">' . self::icon('flask', 17) . '<span>Quality lab</span><span class="kit-count">30</span></a>';
        echo '</nav>';
        echo '<div class="rail-bottom"><div class="rail-tip">' . self::icon('lightbulb', 16) . '<div><strong>Editorial note</strong><span>Specific beats broad. Every strong book starts with a point of view.</span></div></div>';
        echo '<a class="rail-reset" href="user-guide.php">' . self::icon('help', 14) . ' Read the user guide</a></div>';
        echo '</aside>';

        echo '<main class="studio-main">';
        echo '<header class="studio-header"><div class="header-context"><span class="header-kicker">BOOK STRATEGY WORKSPACE</span><span class="header-separator">/</span><span class="header-current">' . $h($current) . '</span></div>';
        echo '<div class="header-actions"><div class="saved-state"><span class="status-dot"></span> Autosaved</div>';
        echo '<a class="header-library-button' . ($active === 'library' ? ' active' : '') . '" href="book-projects.php">' . self::icon('archive', 15) . ' Library <b>' . $libraryCount . '</b></a>';
        echo '<a class="header-icon-button" href="user-guide.php" title="User guide">' . self::icon('help', 17) . '</a>';
        echo '<span class="avatar-button" title="Local workspace">BI</span></div></header>';
        echo '<div class="studio-progress"><div class="progress-copy"><span>' . $h($progressLabel) . '</span><strong>' . $h($progressValue) . '</strong></div><div class="progress-track"><div class="progress-fill animate-progress-in" style="width:' . $progressPercent . '%"></div></div></div>';
        echo '<div class="studio-content">';
    }

    public static function close(): void
    {
        echo '</div></main></div>';
    }

    /** A small inline icon set (stroke style, currentColor). */
    public static function icon(string $name, int $size = 16): string
    {
        $paths = [
            'book' => '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
            'target' => '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
            'search' => '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
            'layers' => '<path d="m12 2 8.5 4.8a1 1 0 0 1 0 1.7L12 13 3.5 8.5a1 1 0 0 1 0-1.7z"/><path d="m20.5 12-8.5 5-8.5-5"/><path d="m20.5 16-8.5 5-8.5-5"/>',
            'video' => '<path d="m16 13 5.2 3.1a.5.5 0 0 0 .8-.4V8.3a.5.5 0 0 0-.8-.4L16 11"/><rect x="2" y="6" width="14" height="12" rx="2"/>',
            'gauge' => '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
            'clipboard' => '<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/>',
            'pen' => '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
            'sparkles' => '<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3z"/>',
            'archive' => '<rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
            'lightbulb' => '<path d="M15 14c.2-1 .7-1.7 1.5-2.5A5.4 5.4 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6"/><path d="M10 22h4"/>',
            'check' => '<path d="M20 6 9 17l-5-5"/>',
            'help' => '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
            'flask' => '<path d="M10 2v7.5L4.7 18.4A2 2 0 0 0 6.4 21h11.2a2 2 0 0 0 1.7-2.6L14 9.5V2"/><path d="M8.5 2h7"/><path d="M7 16h10"/>',
            'download' => '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
            'edit-list' => '<path d="M12 5H3"/><path d="M9 12H3"/><path d="M11 19H3"/><path d="M17.5 10.5a2.1 2.1 0 0 1 3 3L15 19l-4 1 1-4z"/>',
            'refresh' => '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
            'book-open' => '<path d="M2 4h6a4 4 0 0 1 4 4v12a3 3 0 0 0-3-3H2z"/><path d="M22 4h-6a4 4 0 0 0-4 4v12a3 3 0 0 1 3-3h7z"/>',
            'alert' => '<circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
            'palette' => '<circle cx="13.5" cy="6.5" r=".5"/><circle cx="17.5" cy="10.5" r=".5"/><circle cx="8.5" cy="7.5" r=".5"/><circle cx="6.5" cy="12.5" r=".5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.9 0 1.8-.7 1.8-1.8 0-.4-.2-.8-.4-1.1-.3-.3-.4-.6-.4-1.1a1.8 1.8 0 0 1 1.8-1.8H17a5 5 0 0 0 5-5c0-4.9-4.5-9.2-10-9.2z"/>',
        ];
        $body = $paths[$name] ?? $paths['book'];
        return '<svg width="' . $size . '" height="' . $size . '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' . $body . '</svg>';
    }

    public static function projectCount(): int
    {
        $dir = __DIR__ . '/projects';
        if (!is_dir($dir)) {
            return 0;
        }
        return count(glob($dir . '/*.json') ?: []);
    }

    public static function css(): string
    {
        return <<<'CSS'
:root {
  --background: 38 31% 94%; --foreground: 220 29% 16%; --border: 35 18% 82%;
  --card: 40 33% 97%; --card-border: 35 18% 84%;
  --primary: 220 29% 16%; --primary-foreground: 40 33% 97%;
  --secondary: 38 25% 89%; --muted: 36 24% 90%; --muted-foreground: 218 12% 43%;
  --accent: 8 80% 62%; --accent-foreground: 40 33% 97%;
  --destructive: 0 63% 46%; --destructive-foreground: 40 33% 97%;
  --sidebar: 220 29% 16%; --sidebar-foreground: 38 31% 94%; --sidebar-border: 220 22% 25%;
  --app-font-sans: 'DM Sans', ui-sans-serif, system-ui, sans-serif;
  --app-font-serif: 'Newsreader', Georgia, serif;
  --app-font-mono: 'DM Mono', ui-monospace, monospace;
  --shadow-card: 0 14px 35px rgba(47, 43, 31, 0.07);
  --shadow-deep: 0 22px 55px rgba(47, 43, 31, 0.11);
  color-scheme: light;
}
* { box-sizing: border-box; }
html { background: hsl(var(--background)); }
body { margin: 0; min-width: 320px; background: hsl(var(--background)); color: hsl(var(--foreground)); font-family: var(--app-font-sans); font-size: 13px; -webkit-font-smoothing: antialiased; }
button, input, textarea, select { font: inherit; }
button { cursor: pointer; }
a { color: hsl(var(--accent)); text-decoration: none; }
a:hover { text-decoration: underline; }
.serif { font-family: var(--app-font-serif); }
.mono { font-family: var(--app-font-mono); }
@keyframes rise-in { from { opacity: 0; transform: translateY(9px); } to { opacity: 1; transform: translateY(0); } }
@keyframes progress-in { from { width: 0; } }
.animate-rise-in { animation: rise-in .45s cubic-bezier(.22,.8,.24,1) both; }
.animate-progress-in { animation: progress-in .75s ease-out both; }
.noise { position: relative; }
.noise::after { content: ''; pointer-events: none; position: fixed; inset: 0; z-index: 40; opacity: .035; background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.8'/%3E%3C/svg%3E"); mix-blend-mode: multiply; }

/* ── Shell ─────────────────────────────────────────────────────────── */
.studio-shell { background: hsl(var(--background)); color: hsl(var(--foreground)); display: flex; min-height: 100dvh; }
.studio-rail { background: hsl(var(--sidebar)); color: hsl(var(--sidebar-foreground)); width: 286px; min-height: 100dvh; padding: 28px 18px 20px; display: flex; flex-direction: column; position: sticky; top: 0; height: 100dvh; flex-shrink: 0; overflow-y: auto; scrollbar-gutter: stable; scrollbar-width: thin; }
.rail-brand { display: flex; align-items: center; gap: 11px; padding: 0 11px; color: inherit; }
.rail-brand:hover { text-decoration: none; }
.brand-mark { width: 35px; height: 35px; display: grid; place-items: center; color: hsl(var(--sidebar)); background: hsl(var(--accent)); border-radius: 10px 10px 10px 3px; flex: 0 0 auto; }
.rail-brand-name { display: block; font-size: 13px; font-weight: 700; letter-spacing: -.02em; }
.rail-brand-sub { display: block; color: hsl(38 20% 69%); font-family: var(--app-font-mono); font-size: 9px; margin-top: 3px; }
.rail-brand-sub span { color: hsl(var(--accent)); padding: 0 2px; }
.rail-project { border-top: 1px solid hsl(var(--sidebar-border)); border-bottom: 1px solid hsl(var(--sidebar-border)); margin: 31px 0 23px; padding: 17px 11px 19px; }
.rail-project-label, .rail-nav-label { color: hsl(38 20% 58%); font-family: var(--app-font-mono); letter-spacing: .13em; font-size: 9px; }
.rail-project-title { font-family: var(--app-font-serif); font-size: 18px; line-height: 1.15; margin: 9px 0 12px; color: hsl(38 31% 94%); max-width: 190px; overflow-wrap: break-word; }
.rail-project-status, .saved-state { display: flex; align-items: center; gap: 6px; color: hsl(38 18% 66%); font-family: var(--app-font-mono); font-size: 9px; }
.status-dot { display: inline-block; width: 6px; height: 6px; border-radius: 99px; background: hsl(76 55% 64%); }
.rail-nav-label { display: block; padding: 0 11px; margin-bottom: 9px; }
.rail-step { border: 1px solid transparent; width: 100%; display: flex; text-align: left; align-items: center; gap: 10px; padding: 10px; background: transparent; border-radius: 9px; color: hsl(38 19% 66%); margin: 3px 0; transition: background .2s ease, color .2s ease, transform .2s ease; }
.rail-step:hover { color: hsl(38 31% 94%); background: hsl(220 22% 21%); transform: translateX(2px); text-decoration: none; }
.rail-step.active { color: hsl(38 31% 94%); background: hsl(220 23% 23%); border-color: hsl(220 17% 32%); box-shadow: inset 3px 0 hsl(var(--accent)); }
.rail-step.complete { color: hsl(38 25% 82%); }
.rail-step.complete .rail-step-icon { color: hsl(76 55% 64%); }
.rail-step-icon { display: grid; place-items: center; width: 24px; height: 24px; flex: 0 0 auto; color: hsl(38 17% 51%); }
.rail-step.active .rail-step-icon { color: hsl(var(--accent)); }
.rail-step-text { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }
.rail-step-text b { font-size: 12px; font-weight: 600; letter-spacing: -.015em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rail-step-text small { font-size: 10px; color: hsl(38 15% 50%); }
.rail-step-index { font-family: var(--app-font-mono); color: hsl(38 15% 46%); font-size: 9px; align-self: flex-start; padding-top: 3px; }
.rail-kit-link { margin-top: 12px; padding: 13px 12px; width: 100%; display: flex; align-items: center; gap: 10px; border: 1px solid hsl(8 45% 41% / .65); background: hsl(8 50% 23% / .55); color: hsl(8 76% 80%); border-radius: 9px; font-size: 12px; font-weight: 600; transition: background .2s ease, transform .2s ease; }
.rail-kit-link:hover, .rail-kit-link.active { background: hsl(8 50% 29%); transform: translateY(-1px); text-decoration: none; }
.rail-writer-link { margin-top: 9px; padding: 12px; width: 100%; display: flex; align-items: center; gap: 10px; border: 1px solid hsl(76 35% 44% / .42); background: hsl(76 25% 24% / .35); color: hsl(76 55% 72%); border-radius: 9px; font-size: 12px; font-weight: 600; transition: background .2s ease, transform .2s ease; }
.rail-writer-link:hover, .rail-writer-link.active { background: hsl(76 27% 29% / .75); transform: translateY(-1px); text-decoration: none; }
.rail-library-link { margin-top: 9px; padding: 12px; width: 100%; display: flex; align-items: center; gap: 10px; border: 1px solid hsl(38 18% 42% / .42); background: hsl(220 21% 21%); color: hsl(38 25% 76%); border-radius: 9px; font-size: 12px; font-weight: 600; transition: background .2s ease, border-color .2s ease, transform .2s ease; }
.rail-library-link:hover, .rail-library-link.active { background: hsl(220 20% 26%); border-color: hsl(38 20% 55% / .55); color: hsl(38 31% 94%); transform: translateY(-1px); text-decoration: none; }
.rail-library-link-prominent { margin: -8px 0 22px; border-color: hsl(var(--accent) / .58); background: hsl(8 50% 23% / .3); color: hsl(38 31% 91%); }
.rail-library-link-prominent:hover, .rail-library-link-prominent.active { background: hsl(8 50% 29% / .72); border-color: hsl(var(--accent)); }
.kit-count { margin-left: auto; font-family: var(--app-font-mono); color: hsl(8 62% 67%); font-size: 10px; }
.rail-nav, .rail-bottom { flex-shrink: 0; }
.rail-bottom { margin-top: auto; padding-top: 22px; }
.rail-tip { display: flex; gap: 10px; padding: 13px 11px; border-radius: 9px; background: hsl(220 25% 20%); color: hsl(75 58% 73%); }
.rail-tip > div { display: flex; flex-direction: column; gap: 4px; }
.rail-tip strong { font-size: 10px; color: hsl(38 31% 91%); }
.rail-tip span { font-size: 10px; line-height: 1.42; color: hsl(38 15% 62%); }
.rail-reset { display: flex; align-items: center; gap: 7px; color: hsl(38 16% 52%); font-size: 10px; margin: 18px 11px 0; }
.rail-reset:hover { color: hsl(38 31% 88%); text-decoration: none; }
.studio-main { min-width: 0; flex: 1; }
.studio-header { min-height: 68px; border-bottom: 1px solid hsl(var(--border)); display: flex; align-items: center; justify-content: space-between; padding: 0 clamp(20px, 4vw, 60px); background: hsl(var(--background) / .82); backdrop-filter: blur(10px); position: sticky; top: 0; z-index: 20; }
.header-context { display: flex; align-items: center; gap: 10px; }
.header-kicker { font-family: var(--app-font-mono); color: hsl(var(--muted-foreground)); font-size: 9px; letter-spacing: .14em; }
.header-separator { color: hsl(var(--border)); }
.header-current { font-size: 12px; font-weight: 600; }
.header-actions { display: flex; align-items: center; gap: 17px; }
.header-library-button { display: inline-flex; align-items: center; gap: 7px; border: 1px solid hsl(var(--border)); border-radius: 7px; padding: 8px 10px; background: hsl(var(--card)); color: hsl(var(--foreground)); font-size: 11px; font-weight: 700; transition: background .2s ease, border-color .2s ease, color .2s ease; }
.header-library-button:hover, .header-library-button.active { border-color: hsl(var(--accent)); background: hsl(8 55% 96%); color: hsl(var(--accent)); text-decoration: none; }
.header-library-button svg { color: hsl(var(--accent)); }
.header-library-button b { min-width: 14px; border-radius: 99px; padding: 2px 4px; background: hsl(var(--accent)); color: white; font-family: var(--app-font-mono); font-size: 8px; line-height: 1; text-align: center; }
.header-icon-button { color: hsl(var(--muted-foreground)); display: grid; place-items: center; }
.header-icon-button:hover { color: hsl(var(--foreground)); }
.avatar-button { background: hsl(var(--primary)); color: hsl(var(--primary-foreground)); width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center; font-family: var(--app-font-mono); font-size: 9px; font-weight: 500; }
.studio-progress { max-width: 1110px; margin: 0 auto; padding: 23px clamp(20px, 4vw, 60px) 0; }
.progress-copy { display: flex; justify-content: space-between; color: hsl(var(--muted-foreground)); font-family: var(--app-font-mono); font-size: 9px; letter-spacing: .08em; text-transform: uppercase; margin-bottom: 8px; }
.progress-copy strong { color: hsl(var(--accent)); font-weight: 500; }
.progress-track { width: 100%; height: 3px; background: hsl(var(--border)); overflow: hidden; }
.progress-fill { height: 100%; background: hsl(var(--accent)); transition: width .5s cubic-bezier(.22,.8,.24,1); }
.studio-content { max-width: 1110px; padding: 0 clamp(20px, 4vw, 60px) 70px; margin: 0 auto; }

/* ── Shared components ─────────────────────────────────────────────── */
.page-intro { display: flex; justify-content: space-between; align-items: end; gap: 25px; padding: 48px 0 35px; }
.page-intro h1 { font-family: var(--app-font-serif); font-size: clamp(36px, 5vw, 57px); font-weight: 500; line-height: .98; letter-spacing: -.045em; max-width: 670px; margin: 14px 0; }
.page-intro p { max-width: 590px; line-height: 1.65; color: hsl(var(--muted-foreground)); font-size: 14px; margin: 0; }
.intro-action { flex: 0 0 auto; padding-bottom: 3px; display: grid; gap: 8px; justify-items: end; }
.section-label { display: block; color: hsl(var(--muted-foreground)); font-family: var(--app-font-mono); font-size: 9px; font-weight: 500; letter-spacing: .14em; text-transform: uppercase; }
.section-label.coral { color: hsl(var(--accent)); }
.paper-card { background: hsl(var(--card)); border: 1px solid hsl(var(--card-border)); border-radius: 12px; box-shadow: var(--shadow-card); }
.card-heading-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 15px; }
.card-heading-row h2 { font-family: var(--app-font-serif); font-size: 25px; font-weight: 500; letter-spacing: -.025em; margin: 7px 0 0; line-height: 1.1; }
.primary-button, .outline-button { display: inline-flex; align-items: center; justify-content: center; gap: 8px; border-radius: 7px; font-size: 11px; font-weight: 700; padding: 11px 15px; transition: transform .2s ease, background .2s ease, border-color .2s ease, color .2s ease, opacity .2s ease; }
.primary-button { background: hsl(var(--primary)); color: hsl(var(--primary-foreground)); border: 1px solid hsl(var(--primary)); }
.primary-button:hover:not(:disabled) { transform: translateY(-2px); background: hsl(220 31% 23%); text-decoration: none; }
.primary-button:disabled { opacity: .38; cursor: not-allowed; }
.outline-button { background: transparent; border: 1px solid hsl(var(--border)); color: hsl(var(--foreground)); }
.outline-button:hover:not(:disabled) { border-color: hsl(var(--accent)); color: hsl(var(--accent)); transform: translateY(-1px); text-decoration: none; }
.draft-download-button { background: hsl(8 67% 52%); border-color: hsl(8 67% 52%); color: hsl(var(--accent-foreground)); }
.draft-download-button:hover:not(:disabled) { background: hsl(8 67% 45%); border-color: hsl(8 67% 45%); }
.text-button { border: 0; background: transparent; color: hsl(var(--muted-foreground)); display: inline-flex; align-items: center; gap: 6px; font-size: 11px; padding: 5px 0; }
.text-button:hover { color: hsl(var(--accent)); }
.agent-callout { display: flex; align-items: flex-start; gap: 9px; margin-top: 15px; padding: 11px 12px; border: 1px solid hsl(var(--accent) / .25); border-radius: 8px; background: hsl(var(--accent) / .06); color: hsl(var(--muted-foreground)); font-size: 10px; line-height: 1.45; }
.agent-callout svg { flex: 0 0 auto; color: hsl(var(--accent)); margin-top: 1px; }
.agent-callout b { color: hsl(var(--foreground)); }
.visual-agent-label { display: inline-flex; align-items: center; gap: 5px; width: fit-content; padding: 5px 8px; border: 1px solid hsl(var(--accent) / .35); border-radius: 999px; color: hsl(var(--accent)); font-family: var(--app-font-mono); font-size: 8px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
.mini-note { display: flex; gap: 11px; align-items: flex-start; background: hsl(38 25% 89%); border: 1px solid hsl(var(--border)); margin-top: 18px; padding: 15px 16px; border-radius: 10px; }
.mini-note-icon { color: hsl(var(--accent)); padding-top: 2px; }
.mini-note strong { display: block; font-family: var(--app-font-mono); font-size: 9px; letter-spacing: .08em; text-transform: uppercase; }
.mini-note p { color: hsl(var(--muted-foreground)); font-size: 11px; line-height: 1.5; margin: 5px 0 0; }
.status-tag { display: inline-flex; align-items: center; gap: 7px; border: 1px solid hsl(76 40% 53% / .34); color: hsl(150 28% 36%); background: hsl(76 46% 75% / .27); border-radius: 99px; padding: 6px 9px; font-family: var(--app-font-mono); font-size: 8px; text-transform: uppercase; letter-spacing: .06em; }

/* Writer options */
.writer-layout { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(265px, .75fr); gap: 18px; }
.writer-options-card { padding: 29px 31px 22px; }
.style-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 17px; }
.style-option { display: flex; align-items: flex-start; gap: 10px; text-align: left; min-height: 66px; padding: 12px; background: transparent; border: 1px solid hsl(var(--border)); border-radius: 8px; color: hsl(var(--foreground)); cursor: pointer; transition: border-color .2s ease, background .2s ease, transform .2s ease; }
.style-option:hover { border-color: hsl(var(--accent) / .55); transform: translateY(-1px); }
.style-option.active { border-color: hsl(var(--accent)); background: hsl(var(--accent) / .08); }
.style-option input { position: absolute; opacity: 0; pointer-events: none; }
.style-radio { width: 16px; height: 16px; flex: 0 0 auto; display: grid; place-items: center; border: 1px solid hsl(var(--border)); border-radius: 50%; color: hsl(var(--accent)); margin-top: 1px; }
.style-radio svg { opacity: 0; transition: opacity .15s ease; }
.style-option.active .style-radio svg { opacity: 1; }
.style-option.active .style-radio { border-color: hsl(var(--accent)); background: hsl(var(--accent)); color: hsl(var(--card)); }
.style-option strong, .style-option small { display: block; }
.style-option strong { font-family: var(--app-font-serif); font-size: 15px; font-weight: 500; line-height: 1.1; }
.style-option small { margin-top: 5px; color: hsl(var(--muted-foreground)); font-size: 9px; line-height: 1.35; }
.style-agent-label { color: hsl(var(--accent)) !important; font-family: var(--app-font-mono); font-size: 8px !important; letter-spacing: .04em; text-transform: uppercase; }
.writer-section-label { color: hsl(var(--muted-foreground)); font-family: var(--app-font-mono); font-size: 9px; letter-spacing: .12em; text-transform: uppercase; font-weight: 500; }
.writer-length-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 15px; border-top: 1px solid hsl(var(--border)); margin-top: 24px; padding-top: 18px; }
.writer-length-row > div:first-child small { color: hsl(var(--muted-foreground)); display: block; font-size: 10px; margin-top: 5px; max-width: 190px; line-height: 1.45; }
.page-control { min-width: min(100%, 390px); }
.length-toggle { display: flex; padding: 3px; background: hsl(var(--muted)); border-radius: 7px; gap: 2px; }
.length-toggle button { border: 0; background: transparent; color: hsl(var(--muted-foreground)); font-size: 10px; font-weight: 600; padding: 8px 10px; border-radius: 5px; white-space: nowrap; flex: 1; }
.length-toggle button span { color: hsl(var(--muted-foreground)); font-family: var(--app-font-mono); font-size: 8px; }
.length-toggle button.active { color: hsl(var(--foreground)); background: hsl(var(--card)); box-shadow: 0 1px 3px hsl(var(--foreground) / .08); }
.page-input-row { display: flex; align-items: center; gap: 14px; margin-top: 12px; }
.page-input-row input[type="range"] { flex: 1; accent-color: hsl(var(--accent)); }
.page-number-input { display: flex; align-items: center; gap: 6px; color: hsl(var(--muted-foreground)); font-family: var(--app-font-mono); font-size: 9px; white-space: nowrap; }
.page-number-input input { width: 72px; border: 1px solid hsl(var(--border)); background: hsl(38 30% 96%); color: hsl(var(--foreground)); border-radius: 6px; padding: 7px 8px; font-family: var(--app-font-mono); font-size: 11px; }
.page-range-note { color: hsl(var(--muted-foreground)); display: block; font-family: var(--app-font-mono); font-size: 8px; margin-top: 7px; }
.writer-source-note { display: flex; align-items: center; gap: 8px; color: hsl(var(--muted-foreground)); font-family: var(--app-font-mono); font-size: 9px; border-top: 1px solid hsl(var(--border)); margin-top: 18px; padding-top: 14px; }
.writer-source-note svg { color: hsl(var(--accent)); }
.writer-source-note b { color: hsl(var(--foreground)); font-weight: 500; }
.writer-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin-top: 21px; }
.writer-media-options { display: grid; gap: 13px; border-top: 1px solid hsl(var(--border)); margin-top: 24px; padding-top: 18px; }
.writer-media-options > div:first-child small { display: block; max-width: 560px; color: hsl(var(--muted-foreground)); font-size: 10px; line-height: 1.45; margin-top: 5px; }
.writer-media-options .visual-agent-label { margin-top: 8px; }
.media-option-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); gap: 8px; }
.media-option { display: flex; align-items: flex-start; gap: 8px; min-height: 112px; padding: 11px 10px; border: 1px solid hsl(var(--border)); border-radius: 8px; background: transparent; cursor: pointer; transition: border-color .2s ease, background .2s ease, transform .2s ease; }
.media-option:hover { border-color: hsl(var(--accent) / .55); transform: translateY(-1px); }
.media-option.active { border-color: hsl(var(--accent)); background: hsl(var(--accent) / .08); }
.media-option > input { margin: 2px 0 0; accent-color: hsl(var(--accent)); }
.media-option strong, .media-option small { display: block; }
.media-option strong { font-family: var(--app-font-serif); font-size: 14px; font-weight: 500; line-height: 1.1; }
.media-option small { color: hsl(var(--muted-foreground)); font-size: 9px; line-height: 1.3; margin-top: 5px; }
.media-limit-control { display: flex; align-items: center; justify-content: space-between; gap: 7px; margin-top: 9px; }
.media-limit-control small { margin: 0; line-height: 1.15; }
.media-limit-control input { width: 48px; min-height: 28px; margin: 0; padding: 3px 5px; border: 1px solid hsl(var(--border)); border-radius: 5px; background: hsl(var(--background)); color: hsl(var(--foreground)); font: 600 11px var(--app-font-sans); text-align: center; }
.writer-task-progress { display: grid; gap: 7px; width: 100%; margin-top: 12px; padding: 11px 13px; border: 1px solid hsl(var(--border)); border-radius: 8px; background: hsl(var(--background) / .62); }
.writer-task-progress > div:first-child { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: hsl(var(--muted-foreground)); font-family: var(--app-font-mono); font-size: 9px; letter-spacing: .04em; text-transform: uppercase; }
.writer-task-progress b { color: hsl(var(--foreground)); font-weight: 600; }
.writer-task-track { height: 6px; overflow: hidden; border-radius: 999px; background: hsl(var(--muted)); }
.writer-task-track span { display: block; height: 100%; min-width: 0; border-radius: inherit; background: linear-gradient(90deg, hsl(var(--accent)), hsl(35 82% 58%)); transition: width .35s ease; }

/* Page design panel */
.page-style-panel { margin-top: 18px; padding: 25px 28px 28px; }
.page-style-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.page-style-heading h2 { margin: 8px 0 7px; font-family: var(--app-font-serif); font-size: 26px; font-weight: 500; letter-spacing: -.03em; }
.page-style-heading p { max-width: 650px; margin: 0; color: hsl(var(--muted-foreground)); font-size: 11px; line-height: 1.5; }
.page-style-icon { color: hsl(var(--accent)); flex: 0 0 auto; margin-top: 4px; }
.page-style-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 15px; margin-top: 23px; }
.page-style-field { display: grid; gap: 7px; min-width: 0; color: hsl(var(--muted-foreground)); font-family: var(--app-font-mono); font-size: 8px; letter-spacing: .08em; text-transform: uppercase; align-content: start; }
.page-style-field select, .page-style-field input:not([type="range"]):not([type="color"]):not([type="checkbox"]) { width: 100%; min-height: 35px; border: 1px solid hsl(var(--border)); border-radius: 6px; background: hsl(var(--background)); color: hsl(var(--foreground)); padding: 8px 9px; font-family: var(--app-font-sans); font-size: 11px; letter-spacing: 0; text-transform: none; outline: none; }
.page-style-field select:focus, .page-style-field input:focus { border-color: hsl(var(--accent)); box-shadow: 0 0 0 3px hsl(var(--accent) / .1); }
.page-style-field input[type="color"] { width: 100%; height: 35px; padding: 4px; border: 1px solid hsl(var(--border)); border-radius: 6px; background: hsl(var(--background)); }
.page-style-field input[type="checkbox"] { width: auto; min-height: 0; margin: 0 6px 0 0; accent-color: hsl(var(--accent)); }
.page-style-field label { display: flex; align-items: center; letter-spacing: 0; text-transform: none; font-family: var(--app-font-sans); font-size: 11px; color: hsl(var(--foreground)); }

/* Writer output */
.writer-output { margin-top: 28px; }
.writer-output-header { display: flex; align-items: end; justify-content: space-between; gap: 18px; padding: 25px 0 18px; border-bottom: 1px solid hsl(var(--border)); }
.writer-output-header h2 { font-family: var(--app-font-serif); font-size: 32px; font-weight: 700; line-height: 1; letter-spacing: -.035em; margin: 9px 0 6px; }
.writer-output-header p { color: hsl(var(--muted-foreground)); font-family: var(--app-font-mono); font-size: 9px; margin: 0; text-transform: uppercase; letter-spacing: .07em; }
.draft-export-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.draft-toc { padding: 25px 28px; margin-top: 16px; }
.draft-toc-heading { display: flex; align-items: end; justify-content: space-between; gap: 16px; padding-bottom: 14px; border-bottom: 1px solid hsl(var(--border)); }
.draft-toc-heading h2 { font-family: var(--app-font-serif); font-size: 30px; font-weight: 500; line-height: 1; letter-spacing: -.03em; margin: 9px 0 0; }
.draft-toc-list { list-style: none; margin: 0; padding: 8px 0 0; }
.draft-toc-list li { display: flex; align-items: baseline; justify-content: space-between; gap: 18px; padding: 10px 0; border-bottom: 1px dotted hsl(var(--border)); font-family: var(--app-font-serif); font-size: 16px; }
.draft-toc-list li:last-child { border-bottom: 0; }
.draft-toc-list b { color: hsl(var(--accent)); font-family: var(--app-font-mono); font-size: 11px; }
.draft-toc-list small { color: hsl(var(--muted-foreground)); font-family: var(--app-font-mono); font-size: 9px; white-space: nowrap; }
.draft-list { display: grid; gap: 13px; margin-top: 16px; }
.draft-chapter { display: flex; gap: 20px; padding: 25px 28px; }
.draft-chapter-number { color: hsl(var(--accent)); font-family: var(--app-font-mono); font-size: 11px; padding-top: 8px; width: 24px; flex: 0 0 auto; }
.draft-chapter-body { flex: 1; min-width: 0; }
.draft-chapter-heading h3 { font-family: var(--app-font-serif); font-size: 28px; font-weight: 700; line-height: 1; letter-spacing: -.03em; margin: 8px 0; }
.draft-purpose { color: hsl(var(--accent)); font-family: var(--app-font-mono); font-size: 9px; text-transform: uppercase; letter-spacing: .06em; }
.draft-analysis { max-width: 760px; margin: 9px 0 0; color: hsl(var(--muted-foreground)); font-size: 11px; line-height: 1.5; }
.draft-figure { margin: 22px 0 6px; }
.draft-figure figcaption { color: hsl(var(--muted-foreground)); font-size: 10px; margin-top: 7px; line-height: 1.45; }
.draft-figure figcaption b { color: hsl(var(--accent)); font-family: var(--app-font-mono); font-size: 8px; letter-spacing: .06em; text-transform: uppercase; margin-right: 6px; }
.draft-figure svg { max-width: 100%; height: auto; border: 1px solid hsl(var(--border)); border-radius: 8px; background: hsl(var(--card)); }
.draft-figure table { width: 100%; border-collapse: collapse; font-size: 11px; }
.draft-figure th, .draft-figure td { border: 1px solid hsl(var(--border)); padding: 7px 9px; text-align: left; vertical-align: top; }
.draft-figure th { background: hsl(var(--secondary)); font-family: var(--app-font-mono); font-size: 8px; letter-spacing: .06em; text-transform: uppercase; color: hsl(var(--muted-foreground)); }
.toc-editor { margin-top: 18px; border: 1px solid hsl(var(--border)); border-radius: 10px; background: hsl(var(--background) / .55); }
.toc-editor summary { display: flex; align-items: center; gap: 8px; cursor: pointer; list-style: none; padding: 13px 15px; font-weight: 700; font-size: 11px; }
.toc-editor summary::-webkit-details-marker { display: none; }
.toc-editor summary svg { color: hsl(var(--accent)); }
.toc-editor-rows { padding: 0 15px 15px; }
.toc-row { border-top: 1px solid hsl(var(--border)); padding: 14px 0 10px; }
.toc-row strong { color: hsl(var(--accent)); font-family: var(--app-font-mono); font-size: 9px; letter-spacing: .1em; }
.toc-row input, .toc-row textarea { display: block; width: 100%; border: 1px solid hsl(var(--border)); background: hsl(38 30% 96%); color: hsl(var(--foreground)); border-radius: 7px; padding: 9px 11px; margin-top: 8px; outline: none; resize: vertical; transition: border-color .2s ease, box-shadow .2s ease; }
.toc-row input:first-of-type { font-family: var(--app-font-serif); font-size: 16px; }
.toc-row textarea { min-height: 58px; font-size: 11px; line-height: 1.5; }
.toc-row input:focus, .toc-row textarea:focus { border-color: hsl(var(--accent)); box-shadow: 0 0 0 3px hsl(var(--accent) / .1); }

/* The formatted book page preview keeps its own paper identity. */
.page-preview h4 { margin: 0 0 24px; font-size: 30px; font-weight: 700; line-height: 1.05; }
.page-preview h5 { margin: 24px 0 8px; font-size: 20px; font-weight: 700; }
.page-preview p { color: #343947; line-height: inherit; }
.page-running { color: #697080; font: 10px/1.4 var(--app-font-mono); letter-spacing: .08em; text-align: right; text-transform: uppercase; }
.page-footer { display: flex; justify-content: space-between; gap: 18px; margin-top: 30px; padding-top: 12px; border-top: 1px solid #d8d0c2; color: #697080; font: 10px/1.4 var(--app-font-mono); text-transform: uppercase; }

/* ── Legacy page vocabulary, restyled into the studio look ─────────── */
.studio-content section, .studio-content .panel { background: hsl(var(--card)); border: 1px solid hsl(var(--card-border)); border-radius: 12px; box-shadow: var(--shadow-card); padding: 25px 28px; margin-top: 18px; }
.studio-content table { width: 100%; border-collapse: collapse; margin-top: 18px; font-size: 12px; }
.studio-content th, .studio-content td { text-align: left; padding: 10px 12px; border-bottom: 1px solid hsl(var(--border)); vertical-align: top; }
.studio-content th { color: hsl(var(--muted-foreground)); font-family: var(--app-font-mono); font-size: 8px; text-transform: uppercase; letter-spacing: .1em; }
.empty { border: 1px dashed hsl(var(--border)); border-radius: 12px; padding: 28px; color: hsl(var(--muted-foreground)); margin-top: 24px; background: hsl(var(--card) / .4); }
.toc li { line-height: 1.7; font-size: 12px; }
.studio-content section section { box-shadow: none; }
.eyebrow { display: block; color: hsl(var(--accent)); font-family: var(--app-font-mono); font-size: 9px; font-weight: 500; letter-spacing: .14em; text-transform: uppercase; }
h2, h3 { font-family: var(--app-font-serif); font-weight: 500; letter-spacing: -.025em; line-height: 1.1; }
section h2, form.panel h2 { font-size: 25px; margin: 8px 0 10px; }
p { color: hsl(var(--muted-foreground)); line-height: 1.6; }
label { display: block; color: hsl(var(--foreground)); font-size: 11px; font-weight: 700; margin-bottom: 7px; }
input, select, textarea { box-sizing: border-box; width: 100%; background: hsl(38 30% 96%); border: 1px solid hsl(var(--border)); border-radius: 7px; color: hsl(var(--foreground)); padding: 10px 12px; font-size: 12px; outline: none; transition: border-color .2s ease, box-shadow .2s ease; }
input:focus, select:focus, textarea:focus { border-color: hsl(var(--accent)); box-shadow: 0 0 0 3px hsl(var(--accent) / .1); }
input::placeholder, textarea::placeholder { color: hsl(218 12% 57%); }
input[type="checkbox"], input[type="radio"] { width: auto; accent-color: hsl(var(--accent)); margin-right: 6px; }
input[type="color"] { padding: 4px; min-height: 40px; }
input[type="range"] { border: 0; padding: 0; background: transparent; box-shadow: none; accent-color: hsl(var(--accent)); }
form .grid input, form .grid select { margin-bottom: 14px; }
button[type="submit"], form button { border: 1px solid hsl(var(--primary)); border-radius: 7px; background: hsl(var(--primary)); color: hsl(var(--primary-foreground)); padding: 11px 15px; font-size: 11px; font-weight: 700; transition: transform .2s ease, background .2s ease; }
button[type="submit"]:hover, form button:hover { transform: translateY(-2px); background: hsl(220 31% 23%); }
.secondary, button.secondary { background: transparent; border: 1px solid hsl(var(--border)); color: hsl(var(--foreground)); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; }
.metric, .stat { background: hsl(var(--secondary)); border: 1px solid hsl(var(--border)); border-radius: 10px; padding: 16px 18px; }
.metric strong, .stat strong { display: block; font-family: var(--app-font-serif); font-size: 26px; font-weight: 500; letter-spacing: -.03em; color: hsl(var(--foreground)); }
.metric span, .stat span { color: hsl(var(--muted-foreground)); font-size: 11px; line-height: 1.4; }
.score, .hero-score { color: hsl(var(--accent)); font-family: var(--app-font-serif); font-size: 64px; font-weight: 500; letter-spacing: -.06em; line-height: .9; }
.hero-score small { display: block; font-family: var(--app-font-mono); font-size: 9px; font-weight: 500; letter-spacing: .13em; text-transform: uppercase; color: hsl(var(--muted-foreground)); margin-top: 8px; }
.badge { display: inline-block; border-radius: 999px; padding: 5px 14px; font-size: 11px; font-weight: 700; color: hsl(220 29% 16%); background: hsl(76 46% 75%); }
ul { color: hsl(var(--foreground)); line-height: 1.8; padding-left: 20px; }
ul li { font-size: 12px; }
code { color: hsl(var(--accent)); font-family: var(--app-font-mono); font-size: 11px; }
.error { color: hsl(var(--destructive)); background: hsl(var(--destructive) / .07); border: 1px solid hsl(var(--destructive) / .3); padding: 14px; border-radius: 10px; margin-top: 18px; font-size: 12px; }
.note { color: hsl(var(--muted-foreground)); font-size: 11px; }
.keyword { display: inline-block; background: hsl(var(--accent) / .07); border: 1px solid hsl(var(--accent) / .3); border-radius: 999px; color: hsl(var(--accent)); padding: 6px 12px; margin: 0 6px 8px 0; font-size: 11px; }
.description-preview { background: hsl(38 30% 96%); color: #202431; border: 1px solid hsl(var(--border)); border-radius: 10px; padding: 20px 24px; font-family: var(--app-font-serif); white-space: pre-wrap; line-height: 1.55; }
.check { border-top: 1px solid hsl(var(--border)); padding: 13px 0; display: grid; grid-template-columns: 130px 1fr; gap: 14px; }
.check:first-of-type { border-top: 0; }
.status, .status-pass, .status-warn { font-family: var(--app-font-mono); font-size: 9px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.status.ready, .status-pass { color: hsl(150 30% 40%); }
.status.action, .status-warn { color: hsl(8 67% 52%); }
.status.pending { color: hsl(var(--muted-foreground)); }
.check p { margin: 4px 0 0; font-size: 12px; }
.downloads { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
.downloads a { display: inline-flex; align-items: center; gap: 8px; border-radius: 7px; border: 1px solid hsl(var(--border)); background: transparent; color: hsl(var(--foreground)); padding: 11px 15px; font-size: 11px; font-weight: 700; transition: transform .2s ease, border-color .2s ease, color .2s ease; }
.downloads a:hover { border-color: hsl(var(--accent)); color: hsl(var(--accent)); transform: translateY(-1px); text-decoration: none; }
.downloads a.primary { background: hsl(8 67% 52%); border-color: hsl(8 67% 52%); color: hsl(var(--accent-foreground)); }
.downloads a.primary:hover { background: hsl(8 67% 45%); color: hsl(var(--accent-foreground)); }
.metric-row { display: grid; grid-template-columns: 210px 1fr 46px; gap: 12px; align-items: center; border-top: 1px solid hsl(var(--border)); padding: 9px 0; font-size: 12px; }
.metric-row:first-of-type { border-top: 0; }
.metric-row em { color: hsl(var(--muted-foreground)); font-style: normal; font-size: 10px; display: block; }
.metric-value { text-align: right; font-variant-numeric: tabular-nums; font-weight: 700; font-family: var(--app-font-mono); font-size: 11px; }
.bar { height: 6px; background: hsl(var(--muted)); border-radius: 99px; overflow: hidden; }
.bar span { display: block; height: 100%; background: hsl(var(--accent)); border-radius: 99px; }
details { border: 1px solid hsl(var(--border)); border-radius: 10px; margin-top: 10px; background: hsl(var(--background) / .55); }
summary { cursor: pointer; padding: 12px 15px; font-weight: 700; font-size: 12px; }
details > div { padding: 0 15px 13px; color: hsl(var(--muted-foreground)); font-size: 12px; line-height: 1.6; }
.job-catalog { margin: 20px 0 4px; }
.job-catalog summary { color: hsl(var(--accent)); }
.job-catalog-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; padding: 0 12px 12px; }
.job-card { padding: 12px; border: 1px solid hsl(var(--border)); border-radius: 8px; background: hsl(var(--card)); }
.job-card strong, .job-card span { display: block; }
.job-card strong { font-family: var(--app-font-serif); font-size: 15px; font-weight: 500; color: hsl(var(--foreground)); }
.job-card span { margin-top: 5px; color: hsl(var(--muted-foreground)); font-size: 10px; line-height: 1.45; }
.job-card span b { color: hsl(var(--foreground)); }
.style { display: block; background: hsl(var(--secondary)); border-radius: 10px; padding: 14px; border: 1px solid hsl(var(--border)); }
.style strong, .style span { display: block; }
.style strong { font-family: var(--app-font-serif); font-size: 15px; font-weight: 500; }
.style span { color: hsl(var(--muted-foreground)); font-size: 10px; line-height: 1.4; margin-top: 5px; }
.kit-outline { display: grid; gap: 0; border-top: 1px solid hsl(var(--border)); margin-top: 14px; }
.kit-outline > div { display: flex; align-items: center; gap: 11px; padding: 9px 0; border-bottom: 1px solid hsl(var(--border)); }
.kit-outline span { color: hsl(var(--accent)); font-family: var(--app-font-mono); font-size: 8px; }
.kit-outline b { font-family: var(--app-font-serif); font-size: 14px; font-weight: 500; }
.kit-outline small { margin-left: auto; color: hsl(var(--muted-foreground)); font-size: 10px; text-align: right; }

/* Print: hide the shell chrome, keep the manuscript. */
@media print {
  .studio-rail, .studio-header, .studio-progress, .noise::after { display: none !important; }
  .studio-content section { box-shadow: none; border: 0; }
}

/* Responsive */
@media (max-width: 1000px) {
  .studio-rail { width: 245px; }
  .writer-layout { grid-template-columns: 1fr; }
  .media-option-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .page-style-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 700px) {
  .studio-rail { display: none; }
  .studio-header { min-height: 58px; padding: 0 17px; }
  .header-context { display: none; }
  .studio-progress { padding: 17px 17px 0; }
  .studio-content { padding: 0 17px 45px; }
  .page-intro { display: block; padding: 34px 0 26px; }
  .page-intro h1 { font-size: 39px; }
  .intro-action { margin-top: 18px; justify-items: stretch; }
  .writer-options-card, .studio-content section { padding: 21px 17px; }
  .style-grid { grid-template-columns: 1fr; }
  .writer-length-row { flex-direction: column; align-items: stretch; }
  .writer-actions { flex-direction: column; }
  .writer-actions .primary-button, .writer-actions .outline-button { width: 100%; }
  .media-option-grid { grid-template-columns: 1fr; }
  .draft-chapter { gap: 10px; }
  .check, .metric-row { grid-template-columns: 1fr; gap: 5px; }
  .job-catalog-list { grid-template-columns: 1fr; }
}
CSS;
    }
}
