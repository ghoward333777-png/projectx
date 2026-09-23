<?php

declare(strict_types=1);

namespace MMS\Host;

/**
 * Minimal database contract implemented once per host ($wpdb / Joomla DatabaseInterface).
 *
 * Table names passed to these methods are logical names without the host prefix
 * (for example "mms_entitlements"); implementations add the prefix.
 * Placeholders in $sql use "?" and are bound in order.
 */
interface Db
{
    public function prefix(): string;

    /** @return array<int, array<string, mixed>> */
    public function select(string $sql, array $params = []): array;

    /** @return int inserted auto-increment id */
    public function insert(string $table, array $row): int;

    public function update(string $table, array $row, array $where): int;

    public function delete(string $table, array $where): int;

    public function execute(string $sql, array $params = []): void;

    /** Current UTC time formatted as MySQL DATETIME. */
    public function now(): string;
}
