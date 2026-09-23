<?php

\defined('_JEXEC') or die;

use Joomla\CMS\Language\Text;
use Joomla\CMS\Router\Route;
use Joomla\CMS\Session\Session;

/** @var \Joomla\Component\Mediamarketplace\Administrator\View\Status\HtmlView $this */
$rt = $this->runtime;
$token = Session::getFormToken();
?>
<div class="container-fluid">
<?php if ($rt === null) : ?>
    <div class="alert alert-danger"><?php echo Text::_('COM_MEDIAMARKETPLACE_PLUGIN_DISABLED'); ?></div>
<?php else : ?>
    <table class="table" style="max-width:900px">
        <tr><th scope="row"><?php echo Text::_('COM_MEDIAMARKETPLACE_SERVER'); ?></th>
            <td><?php echo $this->ping ? '<span class="text-success">' . Text::_('COM_MEDIAMARKETPLACE_RUNNING') . '</span> · ' . htmlspecialchars((string) $this->ping['version']) : '<span class="text-danger">' . Text::_('COM_MEDIAMARKETPLACE_NOT_RUNNING') . '</span>'; ?></td></tr>
        <tr><th scope="row"><?php echo Text::_('COM_MEDIAMARKETPLACE_STORE_URL'); ?></th><td><code><?php echo htmlspecialchars($rt->publicUrl()); ?></code></td></tr>
        <tr><th scope="row"><?php echo Text::_('COM_MEDIAMARKETPLACE_PORT'); ?></th><td><code>127.0.0.1:<?php echo (int) $rt->port(); ?></code></td></tr>
        <tr><th scope="row"><?php echo Text::_('COM_MEDIAMARKETPLACE_DATA_DIR'); ?></th><td><code><?php echo htmlspecialchars($rt->dataDir()); ?></code></td></tr>
        <tr><th scope="row"><?php echo Text::_('COM_MEDIAMARKETPLACE_UPLOAD_LIMIT'); ?></th><td><?php echo (int) \MmsRuntime::phpUploadLimitMb(); ?> MB</td></tr>
        <?php if ($this->problem) : ?><tr><th scope="row"><?php echo Text::_('COM_MEDIAMARKETPLACE_PROBLEM'); ?></th><td class="text-danger"><?php echo htmlspecialchars($this->problem); ?></td></tr><?php endif; ?>
    </table>
    <p>
        <a class="btn btn-primary" href="<?php echo Route::_('index.php?option=com_mediamarketplace&view=open'); ?>"><?php echo Text::_('COM_MEDIAMARKETPLACE_MENU_OPEN'); ?></a>
        <a class="btn btn-secondary" href="<?php echo Route::_('index.php?option=com_mediamarketplace&task=restart&' . $token . '=1'); ?>"><?php echo Text::_('COM_MEDIAMARKETPLACE_RESTART'); ?></a>
        <a class="btn btn-outline-danger" href="<?php echo Route::_('index.php?option=com_mediamarketplace&task=stop&' . $token . '=1'); ?>"><?php echo Text::_('COM_MEDIAMARKETPLACE_STOP'); ?></a>
    </p>
    <h3><?php echo Text::_('COM_MEDIAMARKETPLACE_LOG'); ?></h3>
    <pre class="bg-white border p-3" style="max-width:900px;overflow:auto"><?php echo htmlspecialchars($rt->logTail(40)); ?></pre>
    <h3><?php echo Text::_('COM_MEDIAMARKETPLACE_TAGS'); ?></h3>
    <ul>
        <li><code>{mms_showcase view=grid category=slug}</code></li>
        <li><code>{mms_embed kind=widget id=…}</code></li>
        <li><code>{mms_signin label="My media"}</code></li>
    </ul>
<?php endif; ?>
</div>
