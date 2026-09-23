<?php

declare(strict_types=1);

namespace MMS\Host;

/**
 * Everything the shared library needs from WordPress or Joomla.
 * Implemented once per host; faked in tests.
 */
interface Host
{
    public function name(): string; // 'wordpress' | 'joomla'

    public function siteUrl(): string;

    public function currentUser(): ?User;

    /** Capability names are MMS actions: media, widgets, products, protection, settings, reports. */
    public function can(string $action, ?User $user = null): bool;

    public function db(): Db;

    public function settings(): Settings;

    public function files(): Files;

    /** Secret used to derive encryption and signing keys (AUTH_KEY / Joomla secret). */
    public function secretSalt(): string;

    public function schedule(string $job, array $args = [], int $delaySeconds = 0): void;

    /** Dispatch a named event to host hooks; returns the (possibly filtered) payload. */
    public function trigger(string $event, array $payload = []): array;

    public function translate(string $key, array $vars = []): string;

    public function log(string $level, string $message, array $context = []): void;
}
