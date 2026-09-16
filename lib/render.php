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
 * Usage:  php render.php [--format html|md|txt] <input.crv>   # rendered output to stdout
 *         php render.php --meta <input.crv>                   # frontmatter as JSON
 *
 * html (default) applies the faithful extension set; md/txt use carve-php's
 * markdown/plain converters (which flatten interactive constructs natively).
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
use MarkupCarve\Carve\Extension\FencedRenderExtension;
use MarkupCarve\Carve\Extension\InlineFootnotesExtension;
use MarkupCarve\Carve\Extension\ListTableExtension;
use MarkupCarve\Carve\Extension\MathBlockExtension;
use MarkupCarve\Carve\Extension\SmartQuotesExtension;
use MarkupCarve\Carve\Extension\SpoilerExtension;
use MarkupCarve\Carve\Extension\TableOfContentsExtension;
use MarkupCarve\Carve\Extension\TabsExtension;
use MarkupCarve\Carve\Renderer\RenderMode;
use MarkupCarve\Carve\Transform\FilesystemIncludeResolver;
use MarkupCarve\Carve\Transform\IncludeExpander;

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
$format = 'html';
$includeRoot = null;
$rest = [];
for ($i = 0; $i < count($args); $i++) {
    $a = $args[$i];
    if ($a === '--meta') {
        $metaOnly = true;
    } elseif ($a === '--format') {
        $format = $args[++$i] ?? 'html';
    } elseif ($a === '--include-root') {
        $includeRoot = $args[++$i] ?? null;
    } elseif (in_array($a, ['--html', '--md', '--txt'], true)) {
        $format = ltrim($a, '-');
    } else {
        $rest[] = $a;
    }
}
$format = $format === 'md' ? 'md' : ($format === 'txt' ? 'txt' : 'html');
$input = $rest[0] ?? null;
if ($input === null || !is_file($input)) {
    fail('input .crv file not found: ' . ($input ?? '(none)'));
}
$source = file_get_contents($input);
if ($source === false) {
    fail("could not read {$input}");
}
$sourcePath = realpath($input);
$includeRoot ??= dirname($sourcePath);
if (!str_starts_with($includeRoot, DIRECTORY_SEPARATOR) && !preg_match('/^[A-Za-z]:[\\\\\/]/', $includeRoot)) {
    fail('--include-root must be absolute');
}
$rootPath = realpath($includeRoot);
if ($rootPath === false || !is_dir($rootPath)) {
    fail('--include-root must name a readable directory');
}
if ($sourcePath !== $rootPath && !str_starts_with($sourcePath, rtrim($rootPath, DIRECTORY_SEPARATOR) . DIRECTORY_SEPARATOR)) {
    fail('input file must be inside --include-root');
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

// --- html: the faithful converter -------------------------------------------
$converter = $format === 'md'
    ? CarveConverter::markdown()
    : ($format === 'txt' ? CarveConverter::plainText() : new CarveConverter(
        warnings: true,
        safeMode: true,
        mode: RenderMode::STATIC,
    ));
if ($format === 'html') {
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
        FencedRenderExtension::mermaid(),
        FencedRenderExtension::chart(),
        new SmartQuotesExtension(locale: (string) (getenv('CARVE_SMART_LOCALE') ?: 'en')),
    ]);
}

$expander = new IncludeExpander(
    resolver: new FilesystemIncludeResolver($rootPath),
    currentPath: $sourcePath,
    source: $source,
);
$document = $converter->transform($converter->parse($source), $expander);

foreach ($expander->getWarnings() as $warning) {
    $file = $warning->getFile();
    if ($file !== null && str_starts_with($file, $rootPath)) {
        $file = '[include-root]' . substr($file, strlen($rootPath));
    }
    fwrite(STDERR, sprintf("%s:%d:%d %s - %s\n", $file ?? $input, $warning->getLine(), $warning->getColumn(), $warning->getRule(), $warning->getMessage()));
}
$dependenciesFile = getenv('CARVE_DEPENDENCIES_FILE');
if (is_string($dependenciesFile) && $dependenciesFile !== '') {
    $dependencies = array_map(static function ($dependency): array {
        return ['path' => $dependency->getTarget(), 'resolved' => $dependency->isResolved()];
    }, $expander->getDependencies());
    file_put_contents($dependenciesFile, json_encode($dependencies, JSON_UNESCAPED_SLASHES));
}

echo $converter->render($document);
