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
 * Usage:  php render.php [--format html|md|txt] [include options] <input.crv>
 *         php render.php --meta <input.crv>                   # frontmatter as JSON
 *
 * Include options:
 *   --include-root DIR  containment root, relative to the cwd (default: the input's directory)
 *   --no-includes       leave {{ path }} directives literal
 *   --deps FILE         write the files the render read, root-relative, one per line
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
use MarkupCarve\Carve\Node\Document;
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

// --- includes (PART 9 section 19) --------------------------------------------
/**
 * The path below $root, or null when it is not below it. Keeps host paths out
 * of everything this script prints.
 */
function belowRoot(string $path, string $root): ?string
{
    $prefix = rtrim($root, '/') . '/';

    return str_starts_with($path, $prefix) ? substr($path, strlen($prefix)) : null;
}

/**
 * The document with includes expanded, or null to render the source unchanged.
 */
function expandIncludes(CarveConverter $converter, string $source, string $input, ?string $root, bool $off, ?string $depsOut): ?Document
{
    $explicit = $root !== null;
    $deps = [];
    $document = null;
    if (!$off && ($explicit || str_contains($source, '{{'))) {
        $document = expandWithRoot($converter, $source, $input, $root, $explicit, $deps);
    }
    if ($depsOut !== null && file_put_contents($depsOut, implode('', array_map(static fn ($d) => $d . "\n", $deps))) === false) {
        fail("could not write {$depsOut}");
    }

    return $document;
}

/**
 * @param array<string> $deps
 */
function expandWithRoot(CarveConverter $converter, string $source, string $input, ?string $root, bool $explicit, array &$deps): ?Document
{
    $inputReal = (string)realpath($input);
    if (!class_exists(IncludeExpander::class)) {
        if ($explicit) {
            fail('this carve-php has no include support; drop --include-root or upgrade carve-php');
        }
        fwrite(STDERR, "warning: include directives left literal: this carve-php has no include support\n");

        return null;
    }
    try {
        $resolver = new FilesystemIncludeResolver($root ?? dirname($inputReal));
    } catch (RuntimeException $e) {
        fail($e->getMessage());
    }
    $rootReal = (string)realpath($root ?? dirname($inputReal));

    $expander = new IncludeExpander(
        resolver: $resolver,
        currentPath: $inputReal,
        source: $source,
        extensions: $converter->getExtensions(),
    );
    $document = $converter->transform($converter->parse($source), $expander);

    foreach ($expander->getWarnings() as $w) {
        $file = $w->getFile() === null ? null : belowRoot($w->getFile(), $rootReal);
        fwrite(STDERR, 'warning: ' . $w->getMessage() . ' [' . ($w->getRule() ?? 'include') . ']' . ($file === null ? '' : " in {$file}") . "\n");
    }
    if ($expander->getSuppressedWarnings() > 0) {
        fwrite(STDERR, 'warning: ' . $expander->getSuppressedWarnings() . " further include warning(s) suppressed\n");
    }
    foreach ($expander->getDependencies() as $dependency) {
        $relative = $dependency->isResolved() ? belowRoot($dependency->getTarget(), $rootReal) : null;
        if ($relative !== null) {
            $deps[] = $relative;
        }
    }

    return $document;
}

// --- md / txt: carve-php's native flattening converters ---------------------
if ($format === 'md' || $format === 'txt') {
    $flat = $format === 'md' ? CarveConverter::markdown() : CarveConverter::plainText();
    $expanded = expandIncludes($flat, $source, $input, $includeRoot, $noIncludes, $depsOut);
    echo $expanded === null ? $flat->convert($source) : $flat->render($expanded);
    exit(0);
}

// --- html: the faithful converter -------------------------------------------
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
    FencedRenderExtension::mermaid(),
    FencedRenderExtension::chart(),
    new SmartQuotesExtension(locale: (string) (getenv('CARVE_SMART_LOCALE') ?: 'en')),
]);

$expanded = expandIncludes($converter, $source, $input, $includeRoot, $noIncludes, $depsOut);
$html = $expanded === null ? $converter->convert($source) : $converter->render($expanded);

foreach ($converter->getWarnings() as $w) {
    fwrite(STDERR, "warning: {$w}\n");
}

echo $html;
