<?php

namespace Joomla\Plugin\System\Mmsbridge\Extension;

\defined('_JEXEC') or die;

use Joomla\CMS\Plugin\CMSPlugin;
use Joomla\Event\Event;
use Joomla\Event\SubscriberInterface;
use Joomla\Plugin\System\Mmsbridge\Helper\TokenHelper;

/**
 * System plugin: holds the connection settings, replaces {mms_...} tags in content,
 * and builds single sign-on URLs. Everything else runs on the MediaMarketplace server.
 */
final class Mmsbridge extends CMSPlugin implements SubscriberInterface
{
    private const TOKEN_TTL = 300;

    protected $autoloadLanguage = true;

    public static function getSubscribedEvents(): array
    {
        return [
            'onContentPrepare'  => 'onContentPrepare',
            'onBeforeCompileHead' => 'onBeforeCompileHead',
        ];
    }

    public function serverUrl(): string
    {
        return rtrim((string) $this->params->get('server_url', ''), '/');
    }

    public function siteId(): string
    {
        return (string) $this->params->get('site_id', '');
    }

    public function configured(): bool
    {
        return $this->serverUrl() !== '' && $this->siteId() !== '' && (string) $this->params->get('secret', '') !== '';
    }

    /**
     * Embed markup for a kind (showcase, widget, player, cart, sitepass) with parameters.
     *
     * @param array<string,string> $params
     */
    public function embed(string $kind, array $params = []): string
    {
        if (!$this->configured()) {
            return '';
        }
        $attrs = 'data-mms-embed="' . htmlspecialchars($kind, ENT_QUOTES) . '" data-mms-site="' . htmlspecialchars($this->siteId(), ENT_QUOTES) . '"';
        foreach ($params as $k => $v) {
            if ($v === '' || !preg_match('/^[a-z_]+$/', (string) $k)) {
                continue;
            }
            $attrs .= ' data-mms-' . $k . '="' . htmlspecialchars((string) $v, ENT_QUOTES) . '"';
        }
        return '<div class="mms-embed" ' . $attrs . '></div>';
    }

    /** SSO URL for the current user, or null when the visitor is a guest or the plugin is unconfigured. */
    public function ssoUrl(string $return = '/account'): ?string
    {
        $app = $this->getApplication();
        $user = $app->getIdentity();
        if (!$this->configured() || $user === null || $user->guest) {
            return null;
        }
        $token = TokenHelper::sign([
            'sub'   => (string) $user->id,
            'email' => (string) $user->email,
            'name'  => (string) $user->name,
            'host'  => 'joomla',
            'exp'   => time() + self::TOKEN_TTL,
        ], (string) $this->params->get('secret', ''));
        return $this->serverUrl() . '/sso?' . http_build_query(['site' => $this->siteId(), 'token' => $token, 'return' => $return]);
    }

    /** Replaces {mms_showcase view=grid category=x}, {mms_embed kind=widget id=…} and {mms_signin label="My media" return=/account}. */
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
                    $label = $params['label'] ?? 'My media';
                    return '<a class="mms-signin" rel="nofollow" href="' . htmlspecialchars($url, ENT_QUOTES) . '">' . htmlspecialchars($label, ENT_QUOTES) . '</a>';
            }
            return $m[0];
        }, (string) $article->text) ?? $article->text;
    }

    /** Registers the embed loader script once on site pages. */
    public function onBeforeCompileHead(): void
    {
        $app = $this->getApplication();
        if (!$this->configured() || !$app->isClient('site')) {
            return;
        }
        $app->getDocument()->getWebAssetManager()->registerAndUseScript('mmsbridge.embed', $this->serverUrl() . '/embed.js', [], ['defer' => true]);
    }
}
