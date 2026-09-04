<?php

declare(strict_types=1);

/**
 * Site Package Exporter
 *
 * Zips the complete application into a self-contained package that can be
 * uploaded to any PHP 8.1+ hosting account — no database, no Composer, no
 * API keys. The archive includes a plain-language INSTALL.txt so a
 * non-technical user can get the site running.
 */
final class SitePackageExporter
{
    /** Every file that ships in the hosting package. */
    private const FILES = [
        'BookIntelligenceEngine.php',
        'AmazonBookWriter.php',
        'AudiobookProducer.php',
        'IllustrationStudio.php',
        'QualityLab.php',
        'QrCode.php',
        'EpubExporter.php',
        'PrintMediaCompanion.php',
        'WordManuscriptExporter.php',
        'ManuscriptDeveloper.php',
        'BookProjectStore.php',
        'SitePackageExporter.php',
        'StudioTheme.php',
        'index.php',
        'generate-book.php',
        'amazon-book-writer.php',
        'book-lab.php',
        'book-projects.php',
        'user-guide.php',
        'download-app.php',
        'data/teen-jobs.json',
        'bin/synthesize-audiobook.php',
        'bin/generate-images.php',
        'bin/develop-manuscript.php',
        'tests/rich-chapter-contract.php',
        'tests/amazon-book-writer-contract.php',
        'tests/audiobook-contract.php',
        'tests/site-package-contract.php',
        'tests/illustration-contract.php',
        'tests/visual-selection-contract.php',
        'tests/quality-lab-contract.php',
        'tests/epub-contract.php',
        'tests/print-media-contract.php',
        'tests/manuscript-developer-contract.php',
        'README.md',
    ];

    private const PACKAGE_ROOT = 'book-intelligence-studio/';

    /**
     * List the files that will ship, resolved against the app directory.
     *
     * @return array<int, string> Missing files (empty when everything is present).
     */
    public function missingFiles(): array
    {
        $missing = [];
        foreach (self::FILES as $file) {
            if (!is_file(__DIR__ . '/' . $file)) {
                $missing[] = $file;
            }
        }
        return $missing;
    }

    /** @return array<int, string> */
    public function packagedFiles(): array
    {
        return self::FILES;
    }

    /** Build the hosting package and return the .zip bytes. */
    public function export(): string
    {
        if (!class_exists(ZipArchive::class)) {
            throw new RuntimeException('The PHP zip extension is required to build the hosting package.');
        }
        $missing = $this->missingFiles();
        if ($missing !== []) {
            throw new RuntimeException('The hosting package is incomplete; missing: ' . implode(', ', $missing));
        }
        $path = tempnam(sys_get_temp_dir(), 'site');
        if ($path === false) {
            throw new RuntimeException('Could not create a temporary file for the hosting package.');
        }
        $zip = new ZipArchive();
        if ($zip->open($path, ZipArchive::OVERWRITE) !== true) {
            throw new RuntimeException('Could not open the hosting package for writing.');
        }
        foreach (self::FILES as $file) {
            $zip->addFile(__DIR__ . '/' . $file, self::PACKAGE_ROOT . $file);
        }
        $zip->addFromString(self::PACKAGE_ROOT . 'INSTALL.txt', $this->installGuide());
        $zip->close();
        $bytes = file_get_contents($path);
        unlink($path);
        if ($bytes === false) {
            throw new RuntimeException('Could not read the generated hosting package.');
        }
        return $bytes;
    }

    public function installGuide(): string
    {
        return <<<'TXT'
BOOK INTELLIGENCE STUDIO — INSTALL GUIDE
========================================

What you need
-------------
- A web hosting account that runs PHP 8.1 or newer (almost all shared
  hosts do — cPanel, Hostinger, Bluehost, GoDaddy, SiteGround, etc.)
- Nothing else. No database. No Composer. No API keys.

Install in 3 steps
------------------
1. UPLOAD the "book-intelligence-studio" folder from this zip to your
   host's web folder (usually called public_html, htdocs, or www).
   Most hosts let you upload the whole zip in their File Manager and
   click "Extract".

2. OPEN your site in a browser:
   https://your-domain.com/book-intelligence-studio/
   You should see the strategy workspace right away.

3. START WRITING:
   - index.php            -> analyze a book topic
   - generate-book.php    -> edit the chapter list and draft the book
   - amazon-book-writer.php -> build the Amazon publishing package
   - user-guide.php       -> the friendly user guide

Want it at the top of your domain instead? Upload the files inside the
folder directly into public_html and visit https://your-domain.com/.

Try it before uploading (optional)
----------------------------------
On any computer with PHP installed, open a terminal in the folder and run:
    php -S 127.0.0.1:8082
Then visit http://127.0.0.1:8082/ in your browser.

Audiobooks (optional)
---------------------
Everything on the website works with no accounts or keys. Only actual
audiobook AUDIO synthesis needs one of these, run from a terminal:
    php bin/synthesize-audiobook.php --manifest your-manifest.json --out audio/
- Google voices need a Google Cloud Text-to-Speech API key
  (set GOOGLE_TTS_API_KEY, or pass --key).
- ElevenLabs voices need an ElevenLabs API key (ELEVENLABS_API_KEY).
- Your own voice-cloning engine runs with --engine-cmd.
Cloning a recorded human voice requires that person's explicit
consent — the tool will not run cloning jobs without it.

Check the install (optional)
----------------------------
From a terminal in the app folder:
    php tests/rich-chapter-contract.php
    php tests/amazon-book-writer-contract.php
    php tests/audiobook-contract.php
All three should print "... passed".

That's it. Happy publishing!
TXT;
    }
}
