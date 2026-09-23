<?php

\defined('_JEXEC') or die;

use Joomla\CMS\Language\Text;
use Joomla\CMS\Router\Route;
use Joomla\CMS\Session\Session;

/** @var \Joomla\Component\Mediamarketplace\Administrator\View\Virtuemart\HtmlView $this */
$token = Session::getFormToken();
$s = $this->status;
$link = static fn(string $task): string => Route::_('index.php?option=com_mediamarketplace&task=' . $task . '&' . $token . '=1');
?>
<div class="container-fluid">
<?php if (!$this->virtuemartInstalled) : ?>
    <div class="alert alert-info"><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_NOT_INSTALLED'); ?></div>
<?php elseif ($s === null) : ?>
    <div class="alert alert-danger"><?php echo Text::_('COM_MEDIAMARKETPLACE_NOT_RUNNING'); ?></div>
<?php else : ?>
    <p><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_INTRO'); ?></p>
    <table class="table" style="max-width:900px">
        <tr><th scope="row" style="width:240px"><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_MODE'); ?></th><td><b><?php echo $s['mode'] === 'virtuemart' ? 'VirtueMart' : ($s['mode'] === 'woocommerce' ? 'WooCommerce' : Text::_('COM_MEDIAMARKETPLACE_VM_MODE_NATIVE')); ?></b></td></tr>
        <tr><th scope="row"><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_LINKED'); ?></th><td><?php echo (int) ($s['linked']['virtuemart'] ?? 0); ?> / <?php echo (int) $s['products']; ?></td></tr>
        <tr><th scope="row"><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_UNLINKED'); ?></th><td><?php echo $s['unlinked'] === 'hide' ? Text::_('COM_MEDIAMARKETPLACE_VM_UNLINKED_HIDE') : Text::_('COM_MEDIAMARKETPLACE_VM_UNLINKED_NATIVE'); ?></td></tr>
    </table>
    <p>
        <a class="btn btn-primary" href="<?php echo $link('vm_import'); ?>"><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_IMPORT'); ?></a>
        <a class="btn btn-secondary" href="<?php echo $link('vm_refresh'); ?>"><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_REFRESH'); ?></a>
        <a class="btn btn-secondary" href="<?php echo $link('vm_sync'); ?>"><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_SYNC'); ?></a>
    </p>
    <p>
        <?php if ($s['mode'] === 'virtuemart') : ?>
            <a class="btn btn-outline-secondary" href="<?php echo $link('vm_mode_native'); ?>"><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_MODE_TO_NATIVE'); ?></a>
        <?php else : ?>
            <a class="btn btn-success" href="<?php echo $link('vm_mode_virtuemart'); ?>"><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_MODE_TO_VM'); ?></a>
        <?php endif; ?>
        <?php if ($s['unlinked'] === 'hide') : ?>
            <a class="btn btn-outline-secondary" href="<?php echo $link('vm_unlinked_native'); ?>"><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_UNLINKED_SET_NATIVE'); ?></a>
        <?php else : ?>
            <a class="btn btn-outline-secondary" href="<?php echo $link('vm_unlinked_hide'); ?>"><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_UNLINKED_SET_HIDE'); ?></a>
        <?php endif; ?>
    </p>
    <h3><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_PRODUCTS'); ?></h3>
    <table class="table table-striped" style="max-width:900px"><thead><tr><th><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_STORE_PRODUCT'); ?></th><th><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_TYPE'); ?></th><th><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_PRICE'); ?></th><th><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_PRODUCT'); ?></th></tr></thead><tbody>
    <?php foreach ($this->catalog as $p) : ?>
        <tr><td><?php echo htmlspecialchars((string) $p['title']); ?></td><td><?php echo htmlspecialchars((string) $p['type_label']); ?></td><td><?php echo htmlspecialchars((string) $p['currency'] . ' ' . number_format(((int) $p['price_cents']) / 100, 2)); ?></td>
        <td><?php if (!empty($p['external_id'])) : ?><a href="<?php echo Route::_('index.php?option=com_virtuemart&view=product&task=edit&virtuemart_product_id=' . (int) $p['external_id']); ?>">#<?php echo (int) $p['external_id']; ?></a><?php else : ?><span class="text-danger"><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_NOT_LINKED'); ?></span><?php endif; ?></td></tr>
    <?php endforeach; ?>
    </tbody></table>
    <?php if (!empty($s['events'])) : ?>
    <h3><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_EVENTS'); ?></h3>
    <table class="table table-striped" style="max-width:900px"><thead><tr><th><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_KIND'); ?></th><th><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_ORDER'); ?></th><th><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_STATUS'); ?></th><th><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_RESULT'); ?></th><th><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_WHEN'); ?></th></tr></thead><tbody>
    <?php foreach ($s['events'] as $e) : if (($e['system'] ?? '') !== 'virtuemart') { continue; } ?>
        <tr><td><?php echo htmlspecialchars((string) $e['kind']); ?></td><td>#<?php echo htmlspecialchars((string) $e['external_id']); ?></td><td><?php echo htmlspecialchars((string) $e['status']); ?></td><td><?php echo htmlspecialchars((string) $e['result']); ?></td><td><?php echo htmlspecialchars((string) $e['created_at']); ?></td></tr>
    <?php endforeach; ?>
    </tbody></table>
    <?php endif; ?>
    <p class="text-muted"><?php echo Text::_('COM_MEDIAMARKETPLACE_VM_HINT'); ?></p>
<?php endif; ?>
</div>
