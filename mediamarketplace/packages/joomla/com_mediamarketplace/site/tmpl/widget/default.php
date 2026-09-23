<?php

\defined('_JEXEC') or die;

use Joomla\CMS\Language\Text;

/** @var \Joomla\Component\Mediamarketplace\Site\View\Widget\HtmlView $this */
?>
<div class="com-mediamarketplace com-mediamarketplace-widget">
<?php if ($this->problem !== '') : ?>
    <div class="alert alert-warning"><?php echo Text::_($this->problem); ?></div>
<?php else : ?>
    <?php echo $this->html; ?>
<?php endif; ?>
</div>
