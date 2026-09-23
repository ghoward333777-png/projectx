<?php

declare(strict_types=1);

namespace MMS\Host;

/** Host-agnostic view of a logged-in user. */
final class User
{
    /** @param string[] $groups */
    public function __construct(
        public readonly int|string $id,
        public readonly string $email,
        public readonly string $name,
        public readonly array $groups = [],
    ) {
    }
}
