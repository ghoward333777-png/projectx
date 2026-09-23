<?php

declare(strict_types=1);

namespace MMS\Host;

interface Files
{
    /** Absolute path of the public media root (thumbnails, optimised variants). */
    public function publicRoot(): string;

    /** Absolute path of the private media root (protected originals). */
    public function privateRoot(): string;

    /** Public URL of a path relative to the public root. */
    public function publicUrl(string $relativePath): string;
}
