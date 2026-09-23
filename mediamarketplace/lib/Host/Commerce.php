<?php

declare(strict_types=1);

namespace MMS\Host;

/** Commerce engine contract (WooCommerce / VirtueMart). Phase 0 declares it; Phase 1 implements it. */
interface Commerce
{
    public function engine(): string; // 'woocommerce' | 'virtuemart' | 'none'

    public function isAvailable(): bool;

    public function version(): ?string;

    public function cartUrl(): string;

    public function checkoutUrl(): string;

    /** Register a handler called with (orderId, userId, array $items) when an order is paid. */
    public function onOrderPaid(callable $handler): void;

    /** Register a handler called with (orderId, userId, array $items) when an order is refunded or cancelled. */
    public function onOrderRefunded(callable $handler): void;
}
