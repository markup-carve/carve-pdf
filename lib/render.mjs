#!/usr/bin/env node
/**
 * Faithful Carve -> HTML renderer for carve-pdf, JS backend (carve-js).
 *
 * Mirrors render.php: same registered extensions, static mode, raw HTML off
 * (allowRawHtml:false) with always-on URL sanitizing. Produces the same class
 * vocabulary base.css targets. carve-js and carve-php share a cross-impl test
 * corpus, so output is intended to match the PHP backend.
 *
 * Usage:  node render.mjs [--format html|md|txt] [include options] <input.crv>
 *
 * Include options match render.php: --include-root DIR (absolute),
 * --no-includes, --deps FILE.
 *
 * The carve-js package is resolved from $CARVE_JS (a checkout dir or its
 * dist/index.js), falling back to common locations.
 */
import { readFileSync, existsSync, statSync, realpathSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { resolve, dirname, relative, isAbsolute, sep } from "node:path";

function fail(msg) {
  process.stderr.write(`render.mjs: ${msg}\n`);
  process.exit(1);
}

// --- args -------------------------------------------------------------------
let format = "html";
let includeRoot;
let noIncludes = false;
let depsOut;
const rest = [];
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === "--format") format = argv[++i] ?? "html";
  else if (a === "--include-root") includeRoot = argv[++i] ?? fail("--include-root requires a directory");
  else if (a === "--no-includes") noIncludes = true;
  else if (a === "--deps") depsOut = argv[++i] ?? fail("--deps requires a file");
  else if (a === "--html" || a === "--md" || a === "--txt") format = a.slice(2);
  else rest.push(a);
}
format = format === "md" ? "md" : format === "txt" ? "txt" : "html";

const input = rest[0];
if (!input || !existsSync(input)) fail(`input .crv file not found: ${input ?? "(none)"}`);

// --- resolve carve-js entry -------------------------------------------------
// CARVE_JS may be the dist/index.js file OR a checkout directory; try the
// dist path first so a directory value resolves to the file (importing a
// directory throws ERR_UNSUPPORTED_DIR_IMPORT).
const here = new URL(".", import.meta.url).pathname;
const candidates = [
  process.env.CARVE_JS && resolve(process.env.CARVE_JS, "dist/index.js"),
  process.env.CARVE_JS,
  "/media/mark/data/work/git/carve-js/dist/index.js",
  resolve(here, "../../carve-js/dist/index.js"),
  resolve(here, "../node_modules/@markup-carve/carve/dist/index.js"),
].filter(Boolean);

let entry = null;
for (const c of candidates) {
  if (existsSync(c) && statSync(c).isFile()) { entry = c; break; }
}
if (!entry) fail("could not locate carve-js (dist/index.js); set $CARVE_JS");

const carve = await import(pathToFileURL(entry).href);
const {
  carveToHtml, carveToMarkdown, carveToPlainText,
  details, spoiler, tabs, codeGroup, listTable,
  autolink, externalLinks, mathBlock, mermaid, chart,
} = carve;
if (typeof carveToHtml !== "function") fail(`${entry} does not export carveToHtml`);

const source = readFileSync(input, "utf8");

// --- includes (PART 9 section 19) --------------------------------------------
// The path below root, or undefined. Keeps host paths out of everything printed.
const belowRoot = (path, root) => {
  const rel = relative(root, path);
  return rel && !isAbsolute(rel) && rel.split(sep)[0] !== ".." ? rel : undefined;
};

async function loadResolver(explicit) {
  const nodeEntry = resolve(dirname(entry), "node.js");
  if (typeof carve.expandIncludes === "function" && typeof carve.renderDocument === "function" && existsSync(nodeEntry)) {
    return (await import(pathToFileURL(nodeEntry).href)).fileSystemResolver;
  }
  if (explicit) fail("this carve-js has no include support; drop --include-root or upgrade carve-js");
  process.stderr.write("warning: include directives left literal: this carve-js has no include support\n");
  return undefined;
}

// The expanded document, or undefined to render the source unchanged. A
// configured root reaches the resolver as given: it refuses a relative one, and
// resolving it here would contain includes to the working directory. Only the
// derived default is canonicalized.
async function expand(parseExtensions) {
  const explicit = includeRoot !== undefined;
  const deps = [];
  const doc = !noIncludes && (explicit || source.includes("{{"))
    ? await expandWithRoot(parseExtensions, explicit, deps)
    : undefined;
  if (depsOut !== undefined) writeFileSync(depsOut, deps.map((d) => `${d}\n`).join(""));
  return doc;
}

async function expandWithRoot(parseExtensions, explicit, deps) {
  const fileSystemResolver = await loadResolver(explicit);
  if (!fileSystemResolver) return undefined;
  const inputReal = realpathSync(input);
  const root = includeRoot ?? dirname(inputReal);
  let resolver;
  try {
    resolver = fileSystemResolver(root);
  } catch (e) {
    fail(e.message);
  }
  const rootReal = realpathSync(root);
  const parsed = carve.parse(source, { extensions: parseExtensions, positions: true });
  const result = carve.expandIncludes(parsed, source, {
    resolve: resolver, sourcePath: inputReal, extensions: parseExtensions,
  });
  for (const w of result.warnings) {
    const file = w.file === undefined ? undefined : belowRoot(w.file, rootReal);
    process.stderr.write(`warning: ${w.message} [${w.rule}]${file === undefined ? "" : ` in ${file}`}\n`);
  }
  if (result.suppressedWarnings > 0) {
    process.stderr.write(`warning: ${result.suppressedWarnings} further include warning(s) suppressed\n`);
  }
  for (const d of result.dependencies) {
    const rel = d.resolved ? belowRoot(d.id, rootReal) : undefined;
    if (rel !== undefined) deps.push(rel);
  }
  return result.doc;
}

// md / txt: carve-js native flattening converters
if (format === "md" || format === "txt") {
  const doc = await expand([]);
  const target = format === "md" ? "markdown" : "plain";
  if (doc) process.stdout.write(carve.renderDocument(doc, { target }));
  else process.stdout.write(format === "md" ? carveToMarkdown(source) : carveToPlainText(source));
  process.exit(0);
}

// Extensions mirroring the shopware-carve plugin set (admonitions + smart
// typography are core in carve-js, so they need no explicit registration).
// tableOfContents is intentionally omitted so, like the PHP backend, no TOC is
// auto-inserted. carve-js emits <aside>/<h3> where carve-php emits <div>/<p>,
// but base.css styles by class, so the rendered PDF is equivalent.
const extensions = [
  details(), spoiler(), tabs(), codeGroup(), listTable(),
  autolink(), externalLinks({ rel: "nofollow noopener", target: "_blank" }),
  mathBlock(), mermaid(), chart(),
].filter((e) => e);

const renderOptions = { mode: "static", allowRawHtml: false, extensions };
const expanded = await expand(extensions);
process.stdout.write(expanded
  ? carve.renderDocument(expanded, renderOptions)
  : carveToHtml(source, renderOptions));
