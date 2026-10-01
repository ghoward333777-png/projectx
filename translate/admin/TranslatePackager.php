<?php

declare(strict_types=1);

/**
 * Builds the downloadable editions of QueryBook Translate for the admin page:
 *
 *  - android : Android Studio / Gradle project with the web app in assets/www
 *  - ios     : Xcode project (universal iPhone + iPad) with the web app in www/
 *  - pwa     : static web bundle (installable on Android, iPhone and iPad)
 *  - prebuilt binaries found in translate/dist (e.g. the CI-built APK)
 *
 * Each edition can carry a config.json that pre-connects the app to a cloud
 * QueryBook store. Connection stays optional: the app works fully offline.
 */
final class TranslatePackager
{
    private string $root;

    public function __construct(?string $translateRoot = null)
    {
        $this->root = rtrim($translateRoot ?? dirname(__DIR__), '/');
    }

    /** Web-app files every edition ships (relative to translate/). @return string[] */
    public function webFiles(bool $withServiceWorker = true): array
    {
        $files = ['index.html', 'app.css', 'manifest.webmanifest', 'data/languages.json', 'packs/catalog.json'];
        if ($withServiceWorker) {
            $files[] = 'sw.js';
        }
        foreach (['icons', 'src'] as $dir) {
            $files = array_merge($files, $this->walk($dir, ['png', 'svg', 'js']));
        }
        foreach (glob($this->root . '/packs/*/*.json') ?: [] as $p) {
            $files[] = substr($p, strlen($this->root) + 1);
        }
        $files = array_values(array_unique($files));
        sort($files);
        return $files;
    }

    /**
     * The app's runtime config (config.json).
     * @param array<string, mixed> $opts storeUrl, storeKey, storeConnected, gatewayUrl
     * @return array<string, mixed>
     */
    public function config(string $edition, array $opts = []): array
    {
        $cfg = ['edition' => $edition];
        $storeUrl = trim((string) ($opts['storeUrl'] ?? ''));
        if ($storeUrl !== '') {
            if (!preg_match('#^https://#i', $storeUrl) && !preg_match('#^http://(localhost|127\.0\.0\.1)([:/]|$)#i', $storeUrl)) {
                throw new InvalidArgumentException('The store URL must use https://');
            }
            $cfg['storeUrl'] = rtrim($storeUrl, '/') . '/';
            $cfg['storeConnected'] = (bool) ($opts['storeConnected'] ?? true);
            $key = trim((string) ($opts['storeKey'] ?? ''));
            if ($key !== '') {
                $cfg['storeKey'] = $key;
            }
        }
        $gateway = trim((string) ($opts['gatewayUrl'] ?? ''));
        if ($gateway !== '') {
            $cfg['gatewayUrl'] = rtrim($gateway, '/');
        }
        // Cloud enhancement always starts opted out; the user decides on the device.
        $cfg['cloudOptIn'] = false;
        return $cfg;
    }

    /** @param array<string, mixed> $opts */
    public function export(string $edition, array $opts = []): string
    {
        return match ($edition) {
            'android' => $this->zip('QueryBookTranslate-android', $this->androidEntries($opts)),
            'ios' => $this->zip('QueryBookTranslate-ios', $this->iosEntries($opts)),
            'pwa' => $this->zip('querybook-translate-web', $this->pwaEntries($opts)),
            default => throw new InvalidArgumentException("Unknown edition {$edition}"),
        };
    }

    /** Prebuilt binaries in translate/dist. @return array<int, array{file: string, bytes: int, modified: int, platform: string}> */
    public function prebuilt(): array
    {
        $out = [];
        foreach (glob($this->root . '/dist/*.{apk,aab,ipa}', GLOB_BRACE) ?: [] as $f) {
            $ext = strtolower(pathinfo($f, PATHINFO_EXTENSION));
            $out[] = ['file' => basename($f), 'bytes' => (int) filesize($f), 'modified' => (int) filemtime($f), 'platform' => $ext === 'ipa' ? 'ios' : 'android'];
        }
        usort($out, fn ($a, $b) => strcmp($a['file'], $b['file']));
        return $out;
    }

    public function prebuiltPath(string $file): ?string
    {
        foreach ($this->prebuilt() as $p) {
            if ($p['file'] === $file) {
                return $this->root . '/dist/' . $file;
            }
        }
        return null;
    }

    // ------------------------------------------------------------------ editions

    /** @param array<string, mixed> $opts @return array<string, string> zip path → bytes */
    private function androidEntries(array $opts): array
    {
        $entries = [];
        foreach ($this->walk('native/android', null, ['/.gradle/', '/build/', 'local.properties', '/assets/www/']) as $f) {
            $entries[substr($f, strlen('native/android/'))] = $this->read($f);
        }
        foreach ($this->webFiles(false) as $f) {
            $entries['app/src/main/assets/www/' . $f] = $this->read($f);
        }
        $entries['app/src/main/assets/www/config.json'] = $this->json($this->config('android', $opts));
        $entries['BUILD-ANDROID.txt'] = $this->androidReadme();
        return $entries;
    }

    /** @param array<string, mixed> $opts @return array<string, string> */
    private function iosEntries(array $opts): array
    {
        $entries = [];
        foreach ($this->walk('native/ios', null, ['/build/', 'xcuserdata', '/www/']) as $f) {
            $entries[substr($f, strlen('native/ios/'))] = $this->read($f);
        }
        foreach ($this->webFiles(false) as $f) {
            $entries['QueryBookTranslate/www/' . $f] = $this->read($f);
        }
        $entries['QueryBookTranslate/www/config.json'] = $this->json($this->config('ios', $opts));
        $entries['BUILD-IOS.txt'] = $this->iosReadme();
        return $entries;
    }

    /** @param array<string, mixed> $opts @return array<string, string> */
    private function pwaEntries(array $opts): array
    {
        $entries = [];
        foreach ($this->webFiles(true) as $f) {
            $entries[$f] = $this->read($f);
        }
        $entries['config.json'] = $this->json($this->config('web', $opts));
        $entries['INSTALL.txt'] = $this->pwaReadme();
        return $entries;
    }

    // ------------------------------------------------------------------ helpers

    /**
     * @param string[]|null $extensions
     * @param string[] $skip substrings of paths to leave out
     * @return string[] paths relative to translate/
     */
    private function walk(string $dir, ?array $extensions = null, array $skip = []): array
    {
        $base = $this->root . '/' . $dir;
        if (!is_dir($base)) {
            return [];
        }
        $out = [];
        $it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($base, FilesystemIterator::SKIP_DOTS));
        foreach ($it as $file) {
            if (!$file->isFile()) {
                continue;
            }
            $rel = substr($file->getPathname(), strlen($this->root) + 1);
            foreach ($skip as $s) {
                if (str_contains('/' . $rel, $s)) {
                    continue 2;
                }
            }
            if ($extensions !== null && !in_array(strtolower($file->getExtension()), $extensions, true)) {
                continue;
            }
            $out[] = $rel;
        }
        sort($out);
        return $out;
    }

    private function read(string $rel): string
    {
        $bytes = file_get_contents($this->root . '/' . $rel);
        if ($bytes === false) {
            throw new RuntimeException("Missing file {$rel}");
        }
        return $bytes;
    }

    /** @param array<string, mixed> $data */
    private function json(array $data): string
    {
        return json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n";
    }

    /** @param array<string, string> $entries */
    private function zip(string $folder, array $entries): string
    {
        if (!class_exists(ZipArchive::class)) {
            throw new RuntimeException('The PHP zip extension is required to build downloads.');
        }
        $path = tempnam(sys_get_temp_dir(), 'qbt');
        $zip = new ZipArchive();
        if ($path === false || $zip->open($path, ZipArchive::OVERWRITE) !== true) {
            throw new RuntimeException('Could not create the download archive.');
        }
        ksort($entries);
        foreach ($entries as $name => $bytes) {
            $zip->addFromString($folder . '/' . $name, $bytes);
            if (str_ends_with($name, '.sh')) {
                $zip->setExternalAttributesName($folder . '/' . $name, ZipArchive::OPSYS_UNIX, 0755 << 16);
            }
        }
        $zip->close();
        $bytes = (string) file_get_contents($path);
        unlink($path);
        return $bytes;
    }

    private function androidReadme(): string
    {
        return <<<TXT
        QueryBook Translate — Android (phones and tablets)
        ==================================================

        The app runs fully offline: the translation engine, language registry and
        packs are inside assets/www. config.json holds the optional cloud QueryBook
        store connection chosen on the admin page.

        Build an installable APK
          1. Install Android Studio (or the Android SDK + JDK 17).
          2. Open this folder in Android Studio and let Gradle sync.
          3. Build ▸ Build APK(s)  — or on the command line:  gradle assembleDebug
             (output: app/build/outputs/apk/debug/app-debug.apk)
          4. Copy the APK to the phone/tablet and open it (allow "Install unknown apps"
             for internal distribution), or publish a signed bundle to Google Play:
             Build ▸ Generate Signed Bundle / APK.

        Speech uses the device's own engines: Android SpeechRecognizer (on-device
        where the device supports it; download offline speech packs in Settings ▸
        System ▸ Languages) and Text-to-speech voices installed on the device.

        TXT;
    }

    private function iosReadme(): string
    {
        return <<<TXT
        QueryBook Translate — iPhone and iPad
        =====================================

        One universal app for iPhone and iPad (iOS/iPadOS 16+). The translation
        engine, registry and packs are inside QueryBookTranslate/www and work fully
        offline. config.json holds the optional cloud QueryBook store connection.

        Build and install
          1. On a Mac with Xcode 15 or newer, open QueryBookTranslate.xcodeproj.
          2. Select the QueryBookTranslate target ▸ Signing & Capabilities and pick
             your Apple Developer team (a free personal team works for your own devices).
          3. Plug in the iPhone or iPad, choose it as the run destination, press Run.
          4. For wider internal distribution: Product ▸ Archive, then distribute via
             TestFlight, Ad Hoc or your enterprise program.

        No Mac? Install the web edition instead: open the app URL in Safari on the
        iPhone/iPad ▸ Share ▸ Add to Home Screen. It runs offline after first launch.

        Speech uses Apple's recognizer (on-device when the language supports it) and
        the voices installed on the device (Settings ▸ Accessibility ▸ Spoken Content).

        TXT;
    }

    private function pwaReadme(): string
    {
        return <<<TXT
        QueryBook Translate — web edition (installable app)
        ===================================================

        Upload this folder to any static or PHP web host with HTTPS. Then:
          • Android: open the URL in Chrome ▸ menu ▸ Install app.
          • iPhone / iPad: open the URL in Safari ▸ Share ▸ Add to Home Screen.
        After the first launch the app and installed language packs work offline.
        Local test: php -S 127.0.0.1:8083 -t .   then open http://127.0.0.1:8083/

        TXT;
    }
}
