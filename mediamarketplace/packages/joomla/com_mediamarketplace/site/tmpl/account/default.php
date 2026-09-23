<?php

\defined('_JEXEC') or die;

use Joomla\CMS\Language\Text;

/** @var \Joomla\Component\Mediamarketplace\Site\View\Account\HtmlView $this */
?>
<div class="com-mediamarketplace com-mediamarketplace-account">
<?php if ($this->problem !== '') : ?>
    <div class="alert alert-warning"><?php echo Text::_($this->problem); ?></div>
<?php elseif ($this->loginUrl !== '') : ?>
    <p><?php echo Text::_('COM_MEDIAMARKETPLACE_ACCOUNT_LOGIN_FIRST'); ?></p>
    <p><a class="btn btn-primary" href="<?php echo htmlspecialchars($this->loginUrl, ENT_QUOTES); ?>"><?php echo Text::_('COM_MEDIAMARKETPLACE_ACCOUNT_LOGIN'); ?></a></p>
<?php endif; ?>
</div>
