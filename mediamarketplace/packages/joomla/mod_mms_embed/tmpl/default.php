<?php

\defined('_JEXEC') or die;

/** @var string $html */
if ($html === '') {
    return;
}
?>
<div class="mod-mms-embed <?php echo htmlspecialchars((string) $params->get('moduleclass_sfx', ''), ENT_QUOTES); ?>">
    <?php echo $html; ?>
</div>
