/* Python (tools/export.py) と JS (assets/convert.js) の出力一致テスト。
 * 使い方: node tests/convert.test.mjs
 */
import { readFileSync, readdirSync, writeFileSync, mkdtempSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";

const require = createRequire(import.meta.url);
const OF = require("../assets/convert.js");

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const dirs = ["works", "examples", "products", "events", "places"];
const files = [];
for (const d of dirs) {
  let entries;
  try { entries = readdirSync(path.join(root, d)); } catch { continue; }
  for (const e of entries) if (e.endsWith(".json")) files.push(path.join(d, e));
}

function py(target, file) {
  const out = execFileSync("python3", [path.join(root, "tools/export.py"), target, path.join(root, file)], { encoding: "utf8" });
  const j = JSON.parse(out);
  return target === "schema.org" ? j.jsonld : target === "c2pa" ? j.manifest : j.work;
}

// schema.org の JSON-LD を一時ファイルに書き、Python の import で逆変換した結果を返す
const tmp = mkdtempSync(path.join(tmpdir(), "of-import-"));
function pyImport(ld, name) {
  const p = path.join(tmp, name.replace(/[\/]/g, "_") + ".schemaorg.json");
  writeFileSync(p, JSON.stringify(ld));
  const out = execFileSync("python3", [path.join(root, "tools/export.py"), "import", p], { encoding: "utf8" });
  return JSON.parse(out).work;
}

// JSON のキー順を無視して比較
function norm(v) {
  if (Array.isArray(v)) return v.map(norm);
  if (v && typeof v === "object") {
    const o = {};
    for (const k of Object.keys(v).sort()) o[k] = norm(v[k]);
    return o;
  }
  return v;
}
function eq(a, b) { return JSON.stringify(norm(a)) === JSON.stringify(norm(b)); }

let pass = 0, fail = 0;
for (const f of files) {
  const work = JSON.parse(readFileSync(path.join(root, f), "utf8"));
  // schema.org
  const jsLd = OF.toSchemaOrg(work);
  const pyLd = py("schema.org", f);
  if (eq(jsLd, pyLd)) pass++; else { fail++; console.log("schema.org MISMATCH", f); }
  // c2pa
  const jsC = OF.toC2PA(work);
  const pyC = py("c2pa", f);
  if (eq(jsC, pyC)) pass++; else { fail++; console.log("c2pa MISMATCH", f); }
  // roundtrip: schema.org -> import。JS の逆変換が Python の逆変換と完全一致すること。
  const jsBack = OF.fromSchemaOrg(jsLd);
  const pyBack = pyImport(jsLd, f);
  if (eq(jsBack, pyBack)) pass++; else { fail++; console.log("roundtrip JS/Python MISMATCH", f); }
  // 同一性の保持: id・kind は必ず戻る。元が content_hash を持つなら同じ値が保持される。
  if (jsBack.id === work.id && jsBack.kind === work.kind) pass++;
  else { fail++; console.log("roundtrip id/kind MISMATCH", f, jsBack.id, work.id); }
  if (work.content_hash && jsBack.content_hash !== work.content_hash) { fail++; console.log("roundtrip content_hash NOT preserved", f); }
  else pass++;
}

// content_hash 一致
for (const f of files) {
  const work = JSON.parse(readFileSync(path.join(root, f), "utf8"));
  if (work.content_hash) {
    if (OF.contentHash(work) === work.content_hash) pass++;
    else { fail++; console.log("content_hash MISMATCH", f); }
  }
}

console.log(`\n${pass} passed, ${fail} failed (${files.length} files)`);
process.exit(fail ? 1 : 0);
