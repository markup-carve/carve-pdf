<?php

declare(strict_types=1);

/**
 * Carve -> HTML renderer for carve-pdf, Carve 0.2 (carve-php next2).
 *
 * Renders in STATIC mode with raw HTML off (the 0.2 default) and the default
 * URL policy. Registers the 0.2 standard tabs extension. The other extensions
 * of the 0.1 converter (details, spoiler, list-table, code groups and callouts,
 * math blocks, Mermaid and Chart.js fences, autolink, external links, smart
 * quotes, table of contents) have no carve-php 0.2 counterpart yet; the JS
 * backend has most of them.
 *
 * Usage:  php render.php [--format html|md|txt] [include options] <input.crv>
 *         php render.php --meta <input.crv>   # the frontmatter block as JSON, or null
 *
 * Include options:
 *   --include-root DIR  containment root, relative to the cwd (default: the input's directory)
 *   --no-includes       leave {{ path }} directives literal
 *   --deps FILE         write the files the render read, root-relative, one per line
 *
 * md/txt use the 0.2 `markdown` and `plain` exports of carve-php.
 *
 * The composer autoloader that provides MarkupCarve\Carve is resolved from
 * $CARVE_PHP_AUTOLOAD, falling back to locations relative to this script: the
 * vendor/ beside it, the repo's _deps/carve-php or _deps/php install, a sibling checkout.
 *
 * --probe exits 0 if the autoloader resolves and 1 if it does not, printing
 * nothing, so crv2pdf can pick a backend that actually works.
 */

use MarkupCarve\Carve\Carve;
use MarkupCarve\Carve\Include\FileResolver;
use MarkupCarve\Carve\Node;

function fail(string $msg): never
{
    fwrite(STDERR, "render.php: {$msg}\n");
    exit(1);
}

// --- resolve autoloader -----------------------------------------------------
// --probe answers "can this backend run?" so crv2pdf's `auto` can prefer a
// backend it can actually resolve over one whose interpreter merely exists. It
// needs no input file, so it is settled before anything else.
$probeOnly = in_array('--probe', $argv, true);

$candidates = array_filter([
    getenv('CARVE_PHP_AUTOLOAD') ?: null,
    // Beside the script: what `composer require markup-carve/carve-php` at the
    // repo root lays down.
    __DIR__ . '/../vendor/autoload.php',
    // The repo's own dependency install, which CI builds and uses.
    __DIR__ . '/../_deps/carve-php/vendor/autoload.php',
    __DIR__ . '/../_deps/php/vendor/autoload.php',
    // A sibling checkout, for working on the plugin and carve-pdf together.
    __DIR__ . '/../../shopware-carve/vendor/autoload.php',
]);
$autoload = null;
foreach ($candidates as $c) {
    if (is_file($c)) {
        $autoload = $c;
        break;
    }
}
// Falling through from an unusable $CARVE_PHP_AUTOLOAD would otherwise load a
// different engine than the one asked for, without saying so.
$envAutoload = getenv('CARVE_PHP_AUTOLOAD') ?: null;
if ($envAutoload !== null && $autoload !== null && $autoload !== $envAutoload && !$probeOnly) {
    fwrite(STDERR, "render.php: ignoring \$CARVE_PHP_AUTOLOAD={$envAutoload}: not a file, using {$autoload}\n");
}
if ($autoload === null) {
    if ($probeOnly) {
        exit(1);
    }
    fail('could not locate a composer autoloader providing MarkupCarve\\Carve; set $CARVE_PHP_AUTOLOAD');
}
require $autoload;

// Carve 0.2 only: its one entry point is the static class Carve.
if (!class_exists(Carve::class) || !method_exists(Carve::class, 'render')) {
    if ($probeOnly) {
        exit(1);
    }
    fail("autoloader {$autoload} does not provide the Carve 0.2 entry point MarkupCarve\\Carve\\Carve");
}
if ($probeOnly) {
    exit(0);
}

/**
 * A root typed as a flag means the current directory. The engine resolver
 * refuses a relative root, which stays right for one read from configuration.
 */
function typedRoot(string $value): string
{
    if ($value === '') {
        fail('--include-root requires a directory');
    }
    if (preg_match('~^(?:/|\\\\|[A-Za-z]:[/\\\\])~', $value) === 1) {
        return $value;
    }

    return getcwd() . DIRECTORY_SEPARATOR . $value;
}

// --- args -------------------------------------------------------------------
$args = array_slice($argv, 1);
$metaOnly = false;
$format = 'html';
$includeRoot = null;
$noIncludes = false;
$depsOut = null;
$rest = [];
for ($i = 0; $i < count($args); $i++) {
    $a = $args[$i];
    if ($a === '--meta') {
        $metaOnly = true;
    } elseif ($a === '--format') {
        $format = $args[++$i] ?? 'html';
    } elseif (in_array($a, ['--html', '--md', '--txt'], true)) {
        $format = ltrim($a, '-');
    } elseif ($a === '--include-root') {
        $includeRoot = typedRoot($args[++$i] ?? '');
    } elseif ($a === '--no-includes') {
        $noIncludes = true;
    } elseif ($a === '--deps') {
        $depsOut = $args[++$i] ?? fail('--deps requires a file');
    } else {
        $rest[] = $a;
    }
}
$format = $format === 'md' ? 'md' : ($format === 'txt' ? 'txt' : 'html');
$input = $rest[0] ?? null;
if ($input === null || !is_file($input)) {
    fail('input .crv file not found: ' . ($input ?? '(none)'));
}
if (!is_readable($input)) {
    fail("cannot read input: {$input}");
}
$source = file_get_contents($input);
if ($source === false) {
    fail("cannot read input: {$input}");
}

// --- frontmatter ------------------------------------------------------------
// The block exactly as the engine parsed it ({format, content} or null), so the
// opener rules are the engine's; meta.py turns it into keys.
if ($metaOnly) {
    $block = null;
    foreach (Carve::parse($source)->children ?? [] as $child) {
        if ($child->type === 'frontmatter') {
            $block = ['format' => $child->f['format'] ?? null, 'content' => $child->f['value'] ?? ''];
        }
        break;
    }
    echo json_encode($block, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit(0);
}

// --- includes (C2-N) ----------------------------------------------------------
/**
 * The options with an include resolver, or without one when includes are off.
 *
 * @param array<string, mixed> $options
 * @param array<string> $deps
 *
 * @return array<string, mixed>
 */
function withIncludes(array $options, string $source, string $input, ?string $root, bool $off, array &$deps): array
{
    if ($off || ($root === null && !str_contains($source, '{{'))) {
        return $options;
    }
    $inputReal = (string)realpath($input);
    $base = $root ?? dirname($inputReal);
    try {
        $resolver = FileResolver::forRoot((string)realpath($base));
    } catch (Throwable $e) {
        fail($e->getMessage());
    }
    $rootReal = (string)realpath($base);
    $file = str_starts_with($inputReal, rtrim($rootReal, '/') . '/') ? substr($inputReal, strlen(rtrim($rootReal, '/')) + 1) : basename($inputReal);
    $options['includes'] = ['resolver' => $resolver, 'file' => $file];
    foreach (Carve::includeDependencies($source, ['includes' => $options['includes'], 'extensions' => $options['extensions'] ?? []]) as $dependency) {
        if ($dependency['read'] && is_string($dependency['file']) && !str_starts_with($dependency['file'], '/') && !in_array($dependency['file'], $deps, true)) {
            $deps[] = $dependency['file'];
        }
    }

    return $options;
}

$deps = [];
$options = withIncludes(['mode' => 'static', 'extensions' => ['carve.tabs']], $source, $input, $includeRoot, $noIncludes, $deps);
if ($depsOut !== null && file_put_contents($depsOut, implode('', array_map(static fn ($d) => $d . "\n", $deps))) === false) {
    fail("could not write {$depsOut}");
}

// --- md / txt -----------------------------------------------------------------
if ($format === 'md' || $format === 'txt') {
    $target = $format === 'md' ? 'markdown' : 'plain';
    $parseOptions = array_intersect_key($options, ['includes' => true, 'extensions' => true]);
    try {
        echo Carve::writeTo($target, Carve::parse($source, $parseOptions));
        exit(0);
    } catch (Throwable $e) {
        fail("{$target} export failed: {$e->getMessage()}");
    }
}

// --- html ---------------------------------------------------------------------
$result = Carve::renderWithDiagnostics($source, $options);
foreach ($result->diagnostics as $d) {
    if (isset($options['includes']) && str_starts_with($d->code, 'include')) {
        $file = is_string($d->file ?? null) && !str_starts_with($d->file, '/') ? " in {$d->file}" : '';
        fwrite(STDERR, "warning: {$d->message} [{$d->code}]{$file}\n");
    }
}

echo $result->html;
