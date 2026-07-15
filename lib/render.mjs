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
import { resolve } from "node:path";

function fail(msg) {
  process.stderr.write(`render.mjs: ${msg}\n`);
  process.exit(1);
}

// --- args -------------------------------------------------------------------
let format = "html";
const rest = [];
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === "--format") format = argv[++i] ?? "html";
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
  autolink, externalLinks, mathBlock, mermaid,
} = carve;
if (typeof carveToHtml !== "function") fail(`${entry} does not export carveToHtml`);

// md / txt: carve-js native flattening converters
if (format === "md") { process.stdout.write(carveToMarkdown(readFileSync(input, "utf8"))); process.exit(0); }
if (format === "txt") { process.stdout.write(carveToPlainText(readFileSync(input, "utf8"))); process.exit(0); }

// Extensions mirroring the shopware-carve plugin set (admonitions + smart
// typography are core in carve-js, so they need no explicit registration).
// tableOfContents is intentionally omitted so, like the PHP backend, no TOC is
// auto-inserted. carve-js emits <aside>/<h3> where carve-php emits <div>/<p>,
// but base.css styles by class, so the rendered PDF is equivalent.
const extensions = [
  details(), spoiler(), tabs(), codeGroup(), listTable(),
  autolink(), externalLinks({ rel: "nofollow noopener", target: "_blank" }),
  mathBlock(), mermaid(),
].filter((e) => e);

const source = readFileSync(input, "utf8");
const htmlOut = carveToHtml(source, {
  mode: "static",
  allowRawHtml: false,
  extensions,
});
process.stdout.write(htmlOut);
