<?php

namespace Joomla\Plugin\System\Mediamarketplace\Extension;

\defined('_JEXEC') or die;

use Joomla\CMS\Plugin\CMSPlugin;
use Joomla\CMS\Uri\Uri;
use Joomla\Event\Event;
use Joomla\Event\SubscriberInterface;

/**
 * Runs the bundled MediaMarketplace server inside this Joomla site.
 *
 *  - https://site/mms/...  is proxied to the server (onAfterInitialise)
 *  - {mms_showcase}, {mms_embed}, {mms_signin} tags in articles
 *  - the component's admin menu entry signs administrators into the server admin
 */
final class Mediamarketplace extends CMSPlugin implements SubscriberInterface
{
    public const MOUNT = 'mms';

    protected $autoloadLanguage = true;
    private ?\MmsRuntime $runtime = null;
    private bool $loaderRegistered = false;

    public static function getSubscribedEvents(): array
    {
        return [
            'onAfterInitialise'   => 'onAfterInitialise',
            'onContentPrepare'    => 'onContentPrepare',
            'onBeforeCompileHead' => 'onBeforeCompileHead',
        ];
    }

    public function runtime(): \MmsRuntime
    {
        if ($this->runtime === null) {
            if (!class_exists('MmsRuntime')) {
                require_once __DIR__ . '/../Runtime/MmsRuntime.php';
            }
            $root = rtrim(Uri::root(), '/');
            $origin = rtrim((string) preg_replace('#^(https?://[^/]+).*$#', '$1', $root), '/');
            $this->runtime = new \MmsRuntime([
                'data_dir'   => $this->dataDir(),
                'bin'        => \dirname(__DIR__, 2) . '/bin/mms-server',
                'public_url' => $root . '/' . self::MOUNT,
                'origin'     => $origin,
                'host'       => 'joomla',
                'site_name'  => (string) $this->getApplication()->get('sitename', 'Joomla'),
            ]);
        }
        return $this->runtime;
    }

    /** Outside the web root when possible; otherwise a protected folder under the site. */
    public function dataDir(): string
    {
        $custom = trim((string) $this->params->get('data_dir', ''));
        if ($custom !== '') {
            return $custom;
        }
        $outside = \dirname(JPATH_ROOT) . '/mms-data';
        return (is_writable(\dirname(JPATH_ROOT)) || is_dir($outside)) ? $outside : JPATH_ROOT . '/media/mms-data';
    }

    /** Proxy /mms/... to the server before Joomla routes the request. */
    public function onAfterInitialise(): void
    {
        $app = $this->getApplication();
        if (!$app->isClient('site')) {
            return;
        }
        $uri = (string) ($_SERVER['REQUEST_URI'] ?? '');
        $path = (string) parse_url($uri, PHP_URL_PATH);
        $base = rtrim((string) Uri::root(true), '/');
        $mount = $base . '/' . self::MOUNT;
        if ($path === $base . '/.well-known/apple-developer-merchantid-domain-association') {
            $this->runtime()->proxy('/' . self::MOUNT . '/.well-known/apple-developer-merchantid-domain-association');
            $app->close();
            return;
        }
        if ($path !== $mount && !str_starts_with($path, $mount . '/')) {
            return;
        }
        $forward = $base !== '' && str_starts_with($uri, $base) ? substr($uri, \strlen($base)) : $uri;
        $this->runtime()->proxy($forward);
        $app->close();
    }

    /** @param array<string,string> $params */
    public function embed(string $kind, array $params = []): string
    {
        $this->loaderRegistered = false;
        return $this->runtime()->embed($kind, $params);
    }

    public function ssoUrl(string $return = '/account', bool $admin = false): ?string
    {
        $user = $this->getApplication()->getIdentity();
        if ($user === null || $user->guest) {
            return null;
        }
        return $this->runtime()->ssoUrl(['id' => $user->id, 'email' => $user->email, 'name' => $user->name], $return, $admin && $user->authorise('core.admin'));
    }

    public function onContentPrepare(Event $event): void
    {
        $args = $event->getArguments();
        $article = $args['subject'] ?? ($args[1] ?? null);
        if (!\is_object($article) || !isset($article->text) || strpos((string) $article->text, '{mms_') === false) {
            return;
        }
        $article->text = preg_replace_callback('/\{mms_(showcase|embed|signin)((?:\s+[a-z_]+=(?:"[^"]*"|[^\s}]+))*)\s*\}/', function (array $m): string {
            $params = [];
            if (preg_match_all('/([a-z_]+)=("([^"]*)"|([^\s}]+))/', $m[2], $pm, PREG_SET_ORDER)) {
                foreach ($pm as $p) {
                    $params[$p[1]] = $p[3] !== '' ? $p[3] : ($p[4] ?? '');
                }
            }
            switch ($m[1]) {
                case 'showcase':
                    return $this->embed('showcase', ['view' => $params['view'] ?? 'grid', 'category' => $params['category'] ?? '']);
                case 'embed':
                    $kind = $params['kind'] ?? 'showcase';
                    unset($params['kind']);
                    return $this->embed($kind, $params);
                case 'signin':
                    $url = $this->ssoUrl($params['return'] ?? '/account');
                    if ($url === null) {
                        return '';
                    }
                    return '<a class="mms-signin" rel="nofollow" href="' . htmlspecialchars($url, ENT_QUOTES) . '">' . htmlspecialchars($params['label'] ?? 'My media', ENT_QUOTES) . '</a>';
            }
            return $m[0];
        }, (string) $article->text) ?? $article->text;
    }

    public function onBeforeCompileHead(): void
    {
        $app = $this->getApplication();
        if (!$app->isClient('site') || $this->loaderRegistered) {
            return;
        }
        $this->loaderRegistered = true;
        $app->getDocument()->getWebAssetManager()->registerAndUseScript('mms.embed', $this->runtime()->publicUrl() . '/embed.js', [], ['defer' => true]);
    }
}
