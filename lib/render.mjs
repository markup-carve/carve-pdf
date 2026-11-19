#!/usr/bin/env node
/**
 * Faithful Carve -> HTML renderer for carve-pdf, JS backend (carve-js).
 *
 * Carve 0.2 (carve-js next2): static mode, raw HTML off (the 0.2 default) and
 * the default URL policy, with the provisional standard extensions of
 * `@markup-carve/carve/extensions`. Produces the class vocabulary base.css
 * targets.
 *
 * Usage:  node render.mjs [--format html|md|txt] [include options] <input.crv>
 *         node render.mjs --meta <input.crv>   # the frontmatter block as JSON, or null
 *
 * Include options match render.php: --include-root DIR (relative to the cwd),
 * --no-includes, --deps FILE.
 *
 * The carve-js package is resolved from $CARVE_JS (a checkout dir or its
 * dist/index.js), falling back to locations relative to this script: the
 * node_modules beside it, the repo's _deps/js install, a sibling checkout.
 *
 * --probe exits 0 if the package resolves and 1 if it does not, printing
 * nothing, so crv2pdf can pick a backend that actually works.
 */
import { readFileSync, existsSync, statSync, realpathSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { resolve, dirname, relative, isAbsolute } from "node:path";

function fail(msg) {
  process.stderr.write(`render.mjs: ${msg}\n`);
  process.exit(1);
}

// --- args -------------------------------------------------------------------
// A root typed as a flag means the current directory. The engine resolver
// refuses a relative root, which stays right for one read from configuration.
function typedRoot(value) {
  if (!value) fail("--include-root requires a directory");
  return resolve(value);
}

let format = "html";
let includeRoot;
let noIncludes = false;
let depsOut;
let metaOnly = false;
const rest = [];
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === "--format") format = argv[++i] ?? "html";
  else if (a === "--meta") metaOnly = true;
  else if (a === "--include-root") includeRoot = typedRoot(argv[++i]);
  else if (a === "--no-includes") noIncludes = true;
  else if (a === "--deps") depsOut = argv[++i] ?? fail("--deps requires a file");
  else if (a === "--html" || a === "--md" || a === "--txt") format = a.slice(2);
  else rest.push(a);
}
format = format === "md" ? "md" : format === "txt" ? "txt" : "html";

// --probe answers "can this backend run?" so crv2pdf's `auto` can prefer a
// backend it can actually resolve over one whose interpreter merely exists. It
// needs no input file, so it is settled before the input is demanded.
const probeOnly = argv.includes("--probe");

const input = rest[0];
if (!probeOnly && (!input || !existsSync(input))) fail(`input .crv file not found: ${input ?? "(none)"}`);

// --- resolve carve-js entry -------------------------------------------------
// CARVE_JS may be the dist/index.js file OR a checkout directory; try the
// dist path first so a directory value resolves to the file (importing a
// directory throws ERR_UNSUPPORTED_DIR_IMPORT).
const here = new URL(".", import.meta.url).pathname;
// CI builds carve-js next2 from its pinned commit into _deps/carve-js.
const candidates = [
  process.env.CARVE_JS && resolve(process.env.CARVE_JS, "dist/index.js"),
  process.env.CARVE_JS,
  // Beside the script: what `npm install @markup-carve/carve` at the repo root
  // lays down, and where the Homebrew formula puts the package (libexec).
  resolve(here, "../node_modules/@markup-carve/carve/dist/index.js"),
  // The repo's own dependency install, which CI builds and uses.
  resolve(here, "../_deps/carve-js/dist/index.js"),
  resolve(here, "../_deps/js/node_modules/@markup-carve/carve/dist/index.js"),
  // A sibling carve-js checkout, for working on the engine and carve-pdf together.
  resolve(here, "../../carve-js/dist/index.js"),
].filter(Boolean);

let entry = null;
for (const c of candidates) {
  if (existsSync(c) && statSync(c).isFile()) { entry = c; break; }
}

// Falling through from an unusable $CARVE_JS would otherwise load a different
// engine than the one asked for, without saying so.
if (process.env.CARVE_JS && entry && !entry.startsWith(resolve(process.env.CARVE_JS)) && !probeOnly) {
  process.stderr.write(
    `render.mjs: ignoring $CARVE_JS=${process.env.CARVE_JS}: no dist/index.js there, using ${entry}\n`,
  );
}

if (!entry) {
  if (probeOnly) process.exit(1);
  fail("could not locate carve-js (dist/index.js); set $CARVE_JS");
}

const carve = await import(pathToFileURL(entry).href);
// Carve 0.2 only: the tree contract 2.0 is how the 0.2 package says what it is.
if (typeof carve.render !== "function" || !String(carve.AST_VERSION ?? "").startsWith("2.")) {
  if (probeOnly) process.exit(1);
  fail(`${entry} is not a Carve 0.2 engine (no render / AST_VERSION 2.x)`);
}
const sibling = (name) => resolve(dirname(entry), name);
const ext = existsSync(sibling("extensions.js")) ? await import(pathToFileURL(sibling("extensions.js")).href) : undefined;
if (!ext) {
  if (probeOnly) process.exit(1);
  fail(`${sibling("extensions.js")} is missing: carve-pdf needs the standard extensions of @markup-carve/carve/extensions`);
}
if (probeOnly) process.exit(0);

let source;
try {
  source = readFileSync(input, "utf8");
} catch (e) {
  fail(`cannot read input: ${input} (${e.code ?? e.message})`);
}

// The frontmatter block exactly as the engine parsed it, or null; meta.py turns it into keys.
if (metaOnly) {
  const fm = carve.parse(source).children.find((node) => node.type === "frontmatter");
  process.stdout.write(JSON.stringify(fm ? { format: fm.format, content: fm.value } : null));
  process.exit(0);
}

// Extensions mirroring the shopware-carve plugin set. Admonitions and smart
// typography are core. 0.1's autolink, externalLinks and tocPlacement have no
// 0.2 extension: external links are rebuilt below as a document transform.
// Diagrams and charts are drawn in Chrome before printing (wrap.py loads Mermaid and Chart.js), so static mode
// writes the same client element as interactive mode instead of the fallback code block (C2-X-052).
const clientSide = (b) => ({
  ...b,
  renderers: Object.fromEntries(Object.entries(b.renderers).map(([name, r]) => [name, { ...r, buildTime: r.render }])),
});
const bundle = ext.withExtensions(
  ext.details(), ext.spoiler(), { extensions: carve.tabsExtensions, renderers: { "carve.tabs": carve.tabsRenderer } },
  ext.codeGroup(), ext.listTable(), ext.mathBlock(), clientSide(ext.mermaid()), clientSide(ext.chart()), ext.codeCallouts(),
  ext.smartQuotes({ locale: process.env.CARVE_SMART_LOCALE || "en" }),
);

// 0.1 externalLinks: an absolute http(s) link opens in a new tab without referrer or opener.
const externalLinks = {
  name: "carve-pdf.externalLinks",
  transform(view) {
    const visit = (node) => {
      if (!node || typeof node !== "object") return;
      if (Array.isArray(node)) { node.forEach(visit); return; }
      if (node.type === "link" && /^https?:\/\//iu.test(node.href ?? "")) {
        const keyValues = (node.attrs?.keyValues ?? []).filter(([key]) => key !== "rel" && key !== "target");
        node.attrs = { ...node.attrs, keyValues: [...keyValues, ["rel", "nofollow noopener"], ["target", "_blank"]] };
      }
      for (const [key, value] of Object.entries(node)) if (key !== "attrs" && typeof value === "object") visit(value);
    };
    visit(view);
    return view;
  },
};

// --- includes (C2-N) ----------------------------------------------------------
// The parsed tree with includes expanded, or the parsed source when includes are off.
async function parseDocument(extensions) {
  const explicit = includeRoot !== undefined;
  const deps = [];
  let tree;
  const resolverEntry = sibling("node.js");
  if (!noIncludes && (explicit || source.includes("{{")) && !existsSync(resolverEntry)) {
    if (explicit) fail("this carve-js has no file resolver (@markup-carve/carve/node); drop --include-root");
    process.stderr.write("warning: include directives left literal: this carve-js has no file resolver\n");
  }
  if (!noIncludes && (explicit || source.includes("{{")) && existsSync(resolverEntry)) {
    const node = await import(pathToFileURL(resolverEntry).href);
    const inputReal = realpathSync(input);
    const root = includeRoot ?? dirname(inputReal);
    let resolver;
    try {
      resolver = node.fileSystemResolver(root);
    } catch (e) {
      fail(e.message);
    }
    const rootReal = realpathSync(root);
    const result = carve.parseWithDiagnostics(source, { extensions, includes: { resolver, file: relative(rootReal, inputReal) } });
    // Resolver ids are root-relative already; an absolute one (allowAbsolute) is kept out of the output.
    const shown = (file) => (file === undefined || isAbsolute(file) ? undefined : file);
    for (const d of result.diagnostics.filter((d) => d.code.startsWith("include"))) {
      const file = shown(d.file);
      process.stderr.write(`warning: ${d.message} [${d.code}]${file === undefined ? "" : ` in ${file}`}\n`);
    }
    if (result.suppressedDiagnostics > 0) {
      process.stderr.write(`warning: ${result.suppressedDiagnostics} further diagnostic(s) suppressed\n`);
    }
    for (const d of carve.includeDependencies(result.document)) {
      const rel = d.read ? shown(d.file) : undefined;
      if (rel !== undefined && !deps.includes(rel)) deps.push(rel);
    }
    tree = result.document;
  } else {
    tree = carve.parse(source, { extensions });
  }
  if (depsOut !== undefined) writeFileSync(depsOut, deps.map((d) => `${d}\n`).join(""));
  return tree;
}

// md / txt: the exports of @markup-carve/carve/export.
if (format === "md" || format === "txt") {
  const exportEntry = sibling("export.js");
  if (!existsSync(exportEntry)) fail(`writer not available yet: ${format === "md" ? "markdown" : "plain"} (no ${exportEntry})`);
  const { toMarkdown, toPlainText } = await import(pathToFileURL(exportEntry).href);
  const tree = await parseDocument(bundle.extensions);
  const result = format === "md" ? toMarkdown(tree) : toPlainText(tree);
  process.stdout.write(result.output);
  process.exit(0);
}

const tree = await parseDocument(bundle.extensions);
const options = { mode: "static", smartTypography: true, extensions: bundle.extensions, renderers: bundle.renderers };
const output = carve.renderWithDocumentTransforms(tree, [...(bundle.transforms ?? []), externalLinks], options);
for (const d of output.diagnostics) {
  if (d.severity === "error") process.stderr.write(`warning: ${d.message} [${d.code}]\n`);
}
process.stdout.write(output.html);
