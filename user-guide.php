<?php declare(strict_types=1); ?>
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>User Guide · Book Intelligence Studio</title>
    <style>
        :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background: #11141c; color: #eef0f6; }
        body { margin: 0; background: radial-gradient(circle at top right, #16321f, #11141c 42%); min-height: 100vh; }
        main { max-width: 860px; margin: 0 auto; padding: 42px 24px 90px; }
        header { border-bottom: 1px solid #36384a; padding-bottom: 28px; }
        .eyebrow { color: #7ee2a8; font-size: 11px; letter-spacing: .16em; text-transform: uppercase; font-weight: 700; }
        h1 { font-size: clamp(34px, 6vw, 56px); line-height: 1; letter-spacing: -.05em; margin: 12px 0 10px; }
        h2 { letter-spacing: -.03em; font-size: 24px; margin: 0 0 6px; }
        h3 { font-size: 16px; margin: 18px 0 6px; }
        p, li { color: #c3c7d4; line-height: 1.7; }
        a { color: #a9ecc6; }
        section { background: #1a1d28; border: 1px solid #343747; border-radius: 18px; padding: 26px 28px; margin-top: 18px; }
        .step { display: flex; gap: 16px; margin-top: 14px; }
        .step-number { flex: 0 0 34px; height: 34px; border-radius: 999px; background: #22452f; color: #7ee2a8; font-weight: 800; display: flex; align-items: center; justify-content: center; }
        .step p { margin: 5px 0 0; }
        .step strong { color: #eef0f6; }
        ul { padding-left: 22px; margin: 8px 0; }
        .tip { background: #1d2a22; border: 1px solid #2f4b3a; border-radius: 10px; padding: 13px 16px; margin-top: 14px; color: #b9e6cc; font-size: 14px; }
        .tip b { color: #7ee2a8; }
        .pages { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; margin-top: 12px; }
        .page-card { background: #222534; border: 1px solid #383b4d; border-radius: 12px; padding: 15px; }
        .page-card strong { display: block; color: #fff; margin-bottom: 5px; }
        .page-card span { color: #aeb2c2; font-size: 13px; line-height: 1.5; }
        .button-link { display: inline-block; border-radius: 999px; background: #7ee2a8; color: #0e2417; padding: 12px 20px; font-weight: 800; text-decoration: none; margin-top: 12px; }
        code { background: #10121a; border: 1px solid #343747; border-radius: 6px; padding: 2px 7px; color: #a9ecc6; font-size: 13px; }
        details { border: 1px solid #343747; border-radius: 10px; margin-top: 10px; background: #1e2130; }
        summary { cursor: pointer; padding: 13px 16px; font-weight: 700; color: #eef0f6; }
        details p { padding: 0 16px 14px; margin: 0; }
        footer { color: #8d91a3; font-size: 12px; margin-top: 26px; text-align: center; }
        nav.menu { display: flex; flex-wrap: wrap; gap: 8px; margin: 18px 0 0; }
        nav.menu a { display: inline-block; background: #1e2c24; border: 1px solid #2f4b3a; border-radius: 999px; color: #a9ecc6; padding: 8px 15px; font-size: 13px; font-weight: 700; text-decoration: none; }
        nav.menu a:hover { background: #24382c; }
        @media (max-width: 700px) { main { padding: 26px 14px 60px; } section { padding: 18px; } }
    </style>
</head>
<body>
<main>
    <header>
        <div class="eyebrow">Book Intelligence Studio · User Guide</div>
        <h1>Write a book. Publish it on Amazon. Start here.</h1>
        <p>This guide walks you through everything in plain language. No experience needed — if you can type a topic, you can make a book.</p>
        <nav class="menu" aria-label="App menu">
            <a href="index.php">🏛 Strategy</a>
            <a href="generate-book.php">📝 Draft</a>
            <a href="amazon-book-writer.php">📦 Amazon Book Writer</a>
            <a href="book-lab.php">🔬 Book Development Lab</a>
            <a href="download-app.php">⬇ Get the app (.zip)</a>
        </nav>
    </header>

    <section>
        <h2>What is this app?</h2>
        <p>Book Intelligence Studio helps you go from <strong>an idea</strong> to <strong>a finished book package</strong>:
        it checks how promising your topic is, plans the chapters, writes a full working draft, and prepares everything
        Amazon asks for when you publish — the title, description, keywords, prices, and the manuscript file itself.
        It even plans your audiobook.</p>
        <p>Everything runs on your own site. No accounts, no monthly fees, no API keys needed for writing.</p>
    </section>

    <section>
        <h2>Your first book in 3 steps</h2>
        <div class="step">
            <div class="step-number">1</div>
            <div><strong>Type your topic.</strong>
                <p>Open <a href="amazon-book-writer.php">the Amazon Book Writer</a> and fill in your book topic
                (for example, “Jobs and work for teens”), who it's for, and your author name.</p>
            </div>
        </div>
        <div class="step">
            <div class="step-number">2</div>
            <div><strong>Pick a voice and a length.</strong>
                <p>Choose one of 13 writing styles — friendly, funny, scholarly, journalistic, and more —
                and how many pages you want (up to 1,000).</p>
            </div>
        </div>
        <div class="step">
            <div class="step-number">3</div>
            <div><strong>Click the big button.</strong>
                <p>“Build the Amazon publishing package” writes the whole book and everything Amazon needs, in seconds.</p>
            </div>
        </div>
        <div class="tip"><b>Tip:</b> nothing is saved anywhere — the same inputs always produce the same book, so you can
        experiment freely and come back any time.</div>
    </section>

    <section>
        <h2>The pages, at a glance</h2>
        <div class="pages">
            <div class="page-card"><strong>index.php · Strategy</strong><span>Is my topic any good? See a best-seller score, who your readers are, and the strongest angles.</span></div>
            <div class="page-card"><strong>generate-book.php · Draft</strong><span>Edit the chapter list before writing, choose the page design (font, margins, headers), and read the draft.</span></div>
            <div class="page-card"><strong>amazon-book-writer.php · Publish</strong><span>The whole package: listing, prices, royalties, checklist, audiobook plan, and all downloads.</span></div>
            <div class="page-card"><strong>book-lab.php · Quality</strong><span>The Book Development Lab: 30 quality metrics with Bronze–Platinum badges, KDP compatibility checks, and the downloadable Best-Seller Production Kit.</span></div>
            <div class="page-card"><strong>user-guide.php · Help</strong><span>You are here! Come back any time.</span></div>
        </div>
    </section>

    <section>
        <h2>What you get</h2>
        <ul>
            <li><strong>A best-seller score</strong> — a friendly estimate of how promising your topic is, and why.</li>
            <li><strong>Your Amazon listing, ready to paste</strong> — title, subtitle, book description, all 7 search keywords, and category suggestions, each kept within Amazon's rules.</li>
            <li><strong>Four editions, priced</strong> — Kindle eBook, paperback, hardcover, and audiobook, with printing costs and how much you earn per copy.</li>
            <li><strong>Figures in every chapter</strong> — diagrams, charts, tables, illustrations, and AI-image prompts, generated after each important topic (see below).</li>
            <li><strong>A quality report card</strong> — 30 metrics, certification badges, and the full Best-Seller Production Kit from the Book Development Lab.</li>
            <li><strong>A publishing checklist</strong> — every step from “review the draft” to “order a proof copy”, marked Ready or Action needed.</li>
            <li><strong>Your files</strong>:
                <ul>
                    <li><strong>Word manuscript (.docx)</strong> — opens in Microsoft Word, already formatted at Amazon's 6×9 book size.</li>
                    <li><strong>KDP manuscript (.html)</strong> — opens in Amazon's free Kindle Create tool.</li>
                    <li><strong>Metadata (.json)</strong> — everything to copy into Amazon's setup screens.</li>
                    <li><strong>Narration script (.txt)</strong> and <strong>audiobook manifest (.json)</strong> — for the audiobook (see below).</li>
                </ul>
            </li>
        </ul>
    </section>

    <section>
        <h2>Pictures for every chapter</h2>
        <p>Your book isn't just words. After each important topic in every chapter, the app automatically creates a figure:</p>
        <ul>
            <li><strong>Diagrams</strong> — the chapter's path, drawn as numbered steps.</li>
            <li><strong>Charts and graphs</strong> — where the chapter spends its attention, and how it builds.</li>
            <li><strong>Tables</strong> — real data side by side (the teen-jobs book gets job-card tables automatically).</li>
            <li><strong>Illustrations</strong> — a drawn emblem, unique to each chapter.</li>
            <li><strong>AI images</strong> — a ready-made art prompt for each chapter, in a matching style.</li>
        </ul>
        <p><strong>Want more?</strong> On the writer page, use <em>“Add an illustration to a chapter”</em>: pick the chapter, the type,
        and describe what it should show. It appears instantly, marked “added by you”, and rides along into every export.</p>
        <p>Diagrams, charts, tables, and illustrations appear immediately — no accounts needed. For the AI images, download the
        <strong>AI-image manifest</strong> and run one command with your Google, OpenAI, or Stability key:</p>
        <p><code>php bin/generate-images.php --manifest your-manifest.json --out images/</code></p>
    </section>

    <section>
        <h2>Check your quality in the Book Development Lab</h2>
        <p>Before you publish, run your book through <a href="book-lab.php">the Lab</a>. It grades the draft on
        <strong>30 honest metrics</strong> — editorial depth, media richness, and format readiness — and awards
        <strong>Bronze, Silver, Gold, or Platinum</strong> badges plus one overall number, the Universal Nonfiction Rating.</p>
        <ul>
            <li><strong>Every metric explains itself</strong> — “0 of 27 chapters end with a takeaway” tells you exactly what to fix.</li>
            <li><strong>KDP compatibility</strong> — 11 checks against Amazon's real rules (page limits, metadata limits, trim, TOC, audio specs).</li>
            <li><strong>Document complexity</strong> — pages, sections, figures, audio hours, case studies, exercises.</li>
            <li><strong>QueryBook learning plan</strong> — a three-question quiz and takeaway for every chapter, ready for study editions.</li>
            <li><strong>The Best-Seller Production Kit</strong> — everything in one downloadable, printable report.</li>
        </ul>
        <div class="tip"><b>Honest numbers:</b> the scores are diagnostics computed from your actual draft to guide revision — nobody can guarantee sales.</div>
    </section>

    <section>
        <h2>Making the audiobook</h2>
        <p>The app plans your audiobook automatically: how long it will run, what it will cost to produce, and a suggested price.
        To turn the plan into actual audio, pick a voice:</p>
        <ul>
            <li><strong>Google voice</strong> — natural AI voices from your Google Cloud account.</li>
            <li><strong>ElevenLabs voice</strong> — very realistic AI voices; can also clone a voice from a recording.</li>
            <li><strong>Your own recording</strong> — clone a sampled voice on your own computer with a local engine.</li>
        </ul>
        <p>Download the <strong>audiobook manifest</strong> from the writer page, then run one command in a terminal:</p>
        <p><code>php bin/synthesize-audiobook.php --manifest your-manifest.json --out audio/</code></p>
        <p>It creates the audio piece by piece and can be safely re-run if it stops — it picks up where it left off.</p>
        <div class="tip"><b>Important:</b> cloning a real person's voice needs that person's clear permission.
        The app will not create cloning jobs until you confirm the speaker has consented. Stock AI voices don't need this.</div>
    </section>

    <section>
        <h2>Putting your book on Amazon</h2>
        <div class="step"><div class="step-number">1</div><div><p>Create a free account at <strong>kdp.amazon.com</strong> (Kindle Direct Publishing).</p></div></div>
        <div class="step"><div class="step-number">2</div><div><p>Click “Create”, then copy your title, description, keywords, and categories from the metadata file.</p></div></div>
        <div class="step"><div class="step-number">3</div><div><p>Upload your manuscript (the Word file works, or open the HTML file in Kindle Create first) and a cover — Amazon's free Cover Creator is fine to start.</p></div></div>
        <div class="step"><div class="step-number">4</div><div><p>Set your prices — the app already suggested prices and shows what you earn per copy.</p></div></div>
        <div class="step"><div class="step-number">5</div><div><p>Order a printed proof, check it, and press Publish. Amazon usually reviews within 72 hours.</p></div></div>
        <div class="tip"><b>Remember:</b> the app's prices and royalties are careful estimates — always confirm the live numbers Amazon shows you before publishing.</div>
    </section>

    <section>
        <h2>Put this app on your own website</h2>
        <p>Want this studio running at your own web address? One click packs the whole app into a zip,
        with a simple install guide inside. Upload it to any ordinary PHP host (cPanel, Hostinger, Bluehost,
        GoDaddy, SiteGround…), extract, and it just works — no database, no setup.</p>
        <a class="button-link" href="download-app.php">Download the app for your website (.zip)</a>
        <p style="font-size: 13px; color: #8d91a3; margin-top: 10px;">Inside the zip: every app file plus INSTALL.txt with the 3-step instructions.</p>
    </section>

    <section>
        <h2>Common questions</h2>
        <details><summary>Do I need any accounts or API keys?</summary>
            <p>Not for writing — everything on the site works with nothing at all. You only need a key (Google or ElevenLabs)
            if you want to generate real audiobook audio, and an Amazon KDP account when you're ready to publish.</p></details>
        <details><summary>Is my book private?</summary>
            <p>Yes. The app runs entirely on your own server and saves nothing. Your topic, draft, and files never leave your site.</p></details>
        <details><summary>Can I edit the book before publishing?</summary>
            <p>Absolutely — that's the idea. Edit the chapter list on the draft page before generating, and edit the Word file
            afterwards like any document. Treat the draft as your strong first version.</p></details>
        <details><summary>The teen-jobs book looks extra detailed. Why?</summary>
            <p>“Jobs and work for teens” is the app's flagship topic: it ships with a hand-built 27-chapter outline and a catalog
            of 120 real starter jobs, woven into the chapters automatically.</p></details>
        <details><summary>Are the sales scores a guarantee?</summary>
            <p>No — they're honest planning estimates to help you compare topics and make decisions. Nobody can promise sales.</p></details>
        <details><summary>Something looks broken. What do I check first?</summary>
            <p>Make sure your host runs PHP 8.1 or newer (it's a one-click setting on most hosts), and that the
            <code>data/teen-jobs.json</code> file was uploaded along with everything else.</p></details>
    </section>

    <footer>Book Intelligence Studio · runs on plain PHP · no data leaves your site</footer>
</main>
</body>
</html>
