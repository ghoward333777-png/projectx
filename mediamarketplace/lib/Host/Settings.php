<?php

declare(strict_types=1);

namespace MMS\Host;

/** Persisted options. Secrets are encrypted by MMS\Settings\Secrets before reaching here. */
interface Settings
{
    public function get(string $key, mixed $default = null): mixed;

    public function set(string $key, mixed $value): void;

    public function delete(string $key): void;
}
