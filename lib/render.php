<?php

declare(strict_types=1);

/**
 * Faithful Carve -> HTML renderer for carve-pdf.
 *
 * Mirrors the shopware-carve plugin's converter (same extension set) so the PDF
 * output matches the storefront/CLI rendering, plus MathBlock and SmartQuotes.
 * Renders in STATIC mode (interactive constructs flattened, no client JS) with
 * safe mode on (raw HTML escaped).
 *
 * Usage:  php render.php <input.crv>            # writes HTML fragment to stdout
 *         php render.php --meta <input.crv>     # writes frontmatter as JSON
 *
 * The composer autoloader that provides MarkupCarve\Carve is resolved from
 * $CARVE_PHP_AUTOLOAD, falling back to a few common locations.
 */

use MarkupCarve\Carve\CarveConverter;
use MarkupCarve\Carve\Extension\AdmonitionExtension;
use MarkupCarve\Carve\Extension\AutolinkExtension;
use MarkupCarve\Carve\Extension\CodeGroupExtension;
use MarkupCarve\Carve\Extension\DetailsExtension;
use MarkupCarve\Carve\Extension\ExternalLinksExtension;
use MarkupCarve\Carve\Extension\InlineFootnotesExtension;
use MarkupCarve\Carve\Extension\ListTableExtension;
use MarkupCarve\Carve\Extension\MathBlockExtension;
use MarkupCarve\Carve\Extension\SmartQuotesExtension;
use MarkupCarve\Carve\Extension\SpoilerExtension;
use MarkupCarve\Carve\Extension\TableOfContentsExtension;
use MarkupCarve\Carve\Extension\TabsExtension;
use MarkupCarve\Carve\Renderer\RenderMode;

function fail(string $msg): never
{
    fwrite(STDERR, "render.php: {$msg}\n");
    exit(1);
}

// --- resolve autoloader -----------------------------------------------------
$candidates = array_filter([
    getenv('CARVE_PHP_AUTOLOAD') ?: null,
    '/media/mark/data/work/git/shopware-carve/vendor/autoload.php',
    __DIR__ . '/../../shopware-carve/vendor/autoload.php',
    __DIR__ . '/../vendor/autoload.php',
]);
$autoload = null;
foreach ($candidates as $c) {
    if (is_file($c)) {
        $autoload = $c;
        break;
    }
}
if ($autoload === null) {
    fail('could not locate a composer autoloader providing MarkupCarve\\Carve; set $CARVE_PHP_AUTOLOAD');
}
require $autoload;

if (!class_exists(CarveConverter::class)) {
    fail("autoloader {$autoload} does not provide MarkupCarve\\Carve\\CarveConverter");
}

// --- args -------------------------------------------------------------------
$args = array_slice($argv, 1);
$metaOnly = false;
if (($args[0] ?? null) === '--meta') {
    $metaOnly = true;
    array_shift($args);
}
$input = $args[0] ?? null;
if ($input === null || !is_file($input)) {
    fail('input .crv file not found: ' . ($input ?? '(none)'));
}
$source = file_get_contents($input);
if ($source === false) {
    fail("could not read {$input}");
}

// --- frontmatter (leading ---<fmt> ... --- block) ---------------------------
function parseFrontmatter(string $src): array
{
    if (!preg_match('/^---[a-z]*\R(.*?)\R---\s*\R/su', $src, $m)) {
        return [];
    }
    $out = [];
    foreach (preg_split('/\R/u', $m[1]) as $line) {
        if (!preg_match('/^([A-Za-z0-9_-]+)\s*:\s*(.*)$/', $line, $kv)) {
            continue;
        }
        $key = $kv[1];
        $val = trim($kv[2]);
        if (strlen($val) >= 2 && ($val[0] === '"' || $val[0] === "'") && $val[-1] === $val[0]) {
            $val = substr($val, 1, -1);
        } elseif (str_starts_with($val, '[') && str_ends_with($val, ']')) {
            $items = array_map('trim', explode(',', substr($val, 1, -1)));
            $val = array_values(array_filter($items, static fn ($s) => $s !== ''));
        }
        $out[$key] = $val;
    }
    return $out;
}

if ($metaOnly) {
    echo json_encode(parseFrontmatter($source), JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit(0);
}

// --- build the faithful converter -------------------------------------------
$converter = new CarveConverter(
    warnings: true,
    safeMode: true,
    mode: RenderMode::STATIC,
);
$converter->addExtensions([
    new AdmonitionExtension(),
    new CodeGroupExtension(),
    new DetailsExtension(),
    new SpoilerExtension(),
    new TabsExtension(),
    new ListTableExtension(),
    new InlineFootnotesExtension(),
    new AutolinkExtension(),
    new ExternalLinksExtension(rel: 'nofollow noopener', target: '_blank'),
    new TableOfContentsExtension(),
    new MathBlockExtension(),
    new SmartQuotesExtension(locale: (string) (getenv('CARVE_SMART_LOCALE') ?: 'en')),
]);

$html = $converter->convert($source);

foreach ($converter->getWarnings() as $w) {
    fwrite(STDERR, "warning: {$w}\n");
}

echo $html;
