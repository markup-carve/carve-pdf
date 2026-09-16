#!/usr/bin/env node
/**
 * Faithful Carve -> HTML renderer for carve-pdf, JS backend (carve-js).
 *
 * Mirrors render.php: same registered extensions, static mode, raw HTML off
 * (allowRawHtml:false) with always-on URL sanitizing. Produces the same class
 * vocabulary base.css targets. carve-js and carve-php share a cross-impl test
 * corpus, so output is intended to match the PHP backend.
 *
 * Usage:  node render.mjs [--format html|md|txt] <input.crv>   # output to stdout
 *
 * The carve-js package is resolved from $CARVE_JS (a checkout dir or its
 * dist/index.js), falling back to common locations.
 */
import { readFileSync, existsSync, statSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { dirname, isAbsolute, relative, resolve } from "node:path";

function fail(msg) {
  process.stderr.write(`render.mjs: ${msg}\n`);
  process.exit(1);
}

// --- args -------------------------------------------------------------------
let format = "html";
let includeRoot;
const rest = [];
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === "--format") format = argv[++i] ?? "html";
  else if (a === "--include-root") includeRoot = argv[++i];
  else if (a === "--html" || a === "--md" || a === "--txt") format = a.slice(2);
  else rest.push(a);
}
format = format === "md" ? "md" : format === "txt" ? "txt" : "html";

const input = rest[0];
if (!input || !existsSync(input)) fail(`input .crv file not found: ${input ?? "(none)"}`);
const inputPath = resolve(input);
includeRoot ??= dirname(inputPath);
if (!isAbsolute(includeRoot)) fail("--include-root must be absolute");
includeRoot = resolve(includeRoot);
const inputRelative = relative(includeRoot, inputPath);
if (inputRelative === ".." || inputRelative.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`) || isAbsolute(inputRelative)) {
  fail("input file must be inside --include-root");
}

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
  parse, resolve: resolveDocument, expandIncludes,
  renderHtml, renderMarkdown, renderPlainText,
  details, spoiler, tabs, codeGroup, listTable,
  autolink, externalLinks, mathBlock, mermaid, chart,
} = carve;
if (typeof expandIncludes !== "function") fail(`${entry} does not provide include expansion`);
const nodeEntry = resolve(dirname(entry), "includes-fs.js");
const { fileSystemResolver } = await import(pathToFileURL(nodeEntry).href);

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

const source = readFileSync(input, "utf8");
const expanded = expandIncludes(parse(source, { extensions, positions: true }), source, {
  resolve: fileSystemResolver(includeRoot),
  sourcePath: inputPath,
});
for (const warning of expanded.warnings) {
  const warningRelative = warning.file ? relative(includeRoot, warning.file) : null;
  const file = warningRelative !== null && warningRelative !== ".." && !warningRelative.startsWith("../") && !isAbsolute(warningRelative)
    ? `[include-root]/${warningRelative}`
    : input;
  process.stderr.write(`${file}:${warning.line ?? 1}:${warning.column ?? 1} ${warning.rule} - ${warning.message}\n`);
}
if (process.env.CARVE_DEPENDENCIES_FILE) {
  const dependencies = expanded.dependencies.map(({ id, resolved }) => ({
    path: id, resolved,
  }));
  const { writeFileSync } = await import("node:fs");
  writeFileSync(process.env.CARVE_DEPENDENCIES_FILE, JSON.stringify(dependencies));
}
const doc = resolveDocument(expanded.doc);
if (format === "md") { process.stdout.write(renderMarkdown(doc)); process.exit(0); }
if (format === "txt") { process.stdout.write(renderPlainText(doc)); process.exit(0); }
const htmlOut = renderHtml(doc, {
  mode: "static",
  allowRawHtml: false,
  extensions,
});
process.stdout.write(htmlOut);
