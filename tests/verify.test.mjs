/* assets/verify.js のブラウザ検証が of.py verify と一致するかのテスト。
 * 使い方: node tests/verify.test.mjs
 */
import { readFileSync, readdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const OFV = require("../assets/verify.js");
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

const works = readdirSync(path.join(root, "works")).filter((f) => f.endsWith(".json"));
let fail = 0;

for (const w of works) {
  const file = path.join("works", w);
  const work = JSON.parse(readFileSync(path.join(root, file), "utf8"));
  const filesByName = {};
  for (const r of work.renditions || []) {
    if (!r.path) continue;
    try {
      filesByName[r.path.split("/").pop()] = new Uint8Array(readFileSync(path.join(root, "works", r.path)));
    } catch (e) { /* 実体なし */ }
  }
  const res = await OFV.verifyWork(work, filesByName);

  let pyOk = true, pyOut = null;
  try {
    pyOut = JSON.parse(execFileSync("python3", [path.join(root, "tools/of.py"), "verify", path.join(root, file)], { encoding: "utf8" }));
  } catch (e) {
    pyOk = false;
    try { pyOut = JSON.parse(e.stdout); } catch (_) {}
  }
  const py = pyOut ? pyOut.ok : pyOk;
  const match = res.ok === py;
  console.log(`${match ? "OK  " : "FAIL"} ${file}  js=${res.ok} py=${py}`);
  if (!match) {
    fail++;
    for (const c of res.checks) console.log("   js", c.status, c.label, "|", c.detail);
    if (pyOut) console.log("   py", JSON.stringify(pyOut, null, 2).slice(0, 600));
  }
}
console.log(fail === 0 ? "\n全て一致" : `\n${fail} 件不一致`);
process.exit(fail === 0 ? 0 : 1);
