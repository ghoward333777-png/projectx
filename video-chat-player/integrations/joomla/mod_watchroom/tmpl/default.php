<?php
declare(strict_types=1);

defined('_JEXEC') or die;

use Joomla\CMS\Factory;
use Joomla\CMS\Language\Text;

/** @var array $embed */
$doc = Factory::getApplication()->getDocument();
$wa = $doc->getWebAssetManager();
$wa->registerAndUseScript('mod_watchroom.embed', $embed['base'] . 'assets/embed.js', [], ['defer' => true]);
$id = 'watch-room-' . $module->id;
if ($embed['error'] !== '') {
    echo '<p class="watch-room-error">' . Text::_($embed['error']) . '</p>';
    return;
}
$opts = ['base' => $embed['base'], 'room' => $embed['room'], 'name' => $embed['name'], 'compact' => $embed['compact'], 'autoplay' => true];
if ($embed['height'] !== '') {
    $opts['aspect'] = 'auto';
}
$js = 'document.addEventListener("DOMContentLoaded",function(){var el=document.getElementById(' . json_encode($id) . ');if(el&&window.WatchRoom){var h=window.WatchRoom.embed(el,' . json_encode($opts) . ');'
    . ($embed['height'] !== '' ? 'h.iframe.style.height=' . json_encode($embed['height']) . ';' : '') . 'el.watchRoom=h;}});';
$wa->addInlineScript($js, ['name' => 'mod_watchroom.init.' . $module->id], [], ['mod_watchroom.embed']);
?>
<div class="watch-room mod-watchroom" id="<?php echo htmlspecialchars($id, ENT_QUOTES, 'UTF-8'); ?>" data-room="<?php echo htmlspecialchars($embed['room'], ENT_QUOTES, 'UTF-8'); ?>"></div>
