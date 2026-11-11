// assets/render.js の純粋部分（WAV エンコード・旋律生成・PDF 組み立て）の回帰テスト。
// canvas / MediaRecorder を使う部分はブラウザ専用なのでここでは扱わない。
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const root = path.dirname(fileURLToPath(import.meta.url)) + "/..";
const R = require(path.join(root, "assets/render.js"));

let pass = 0, fail = 0;
function ok(cond, msg) { if (cond) pass++; else { fail++; console.log("FAIL:", msg); } }

const music = JSON.parse(readFileSync(path.join(root, "examples/sample.music.json"), "utf8"));
const book = JSON.parse(readFileSync(path.join(root, "examples/sample.book.json"), "utf8"));

// --- 決定的な乱数・旋律 ---
const m1 = R.melodyFromWork(music);
const m2 = R.melodyFromWork(music);
ok(m1.notes.length > 0, "旋律に音がある");
ok(m1.durationSec > 0 && m1.durationSec <= 20, "長さが範囲内");
ok(JSON.stringify(m1.notes) === JSON.stringify(m2.notes), "同じ作品から同じ旋律（決定的）");
ok(m1.notes.every(n => n.freq > 0 && n.dur > 0 && n.amp > 0), "各音が正の値");

// --- WAV ---
const wav = R.synthWav(music);
ok(wav.bytes instanceof Uint8Array, "WAV が Uint8Array");
ok(String.fromCharCode(...wav.bytes.slice(0, 4)) === "RIFF", "RIFF ヘッダ");
ok(String.fromCharCode(...wav.bytes.slice(8, 12)) === "WAVE", "WAVE ヘッダ");
// data チャンク長の整合
const dv = new DataView(wav.bytes.buffer);
const dataLen = dv.getUint32(40, true);
ok(wav.bytes.length === 44 + dataLen, "data 長が全体長と一致");
ok(wav.sampleRate === R.SAMPLE_RATE, "sampleRate 一致");
// 無音でない（振幅がゼロでないサンプルがある）
let nonzero = 0;
for (let i = 44; i < wav.bytes.length; i += 2) if (dv.getInt16(i, true) !== 0) nonzero++;
ok(nonzero > 100, "無音ではない（振幅あり）");

// --- PDF 組み立て ---
const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xd9]); // ダミー JPEG
const pdf = R.buildPdf([jpeg, jpeg], 600, 800);
ok(pdf instanceof Uint8Array, "PDF が Uint8Array");
const head = String.fromCharCode(...pdf.slice(0, 8));
ok(head.startsWith("%PDF-1.4"), "PDF ヘッダ");
const tail = String.fromCharCode(...pdf.slice(-7));
ok(tail.includes("%%EOF"), "PDF フッタ");
const text = new TextDecoder("latin1").decode(pdf);
ok(text.includes("/Type /Catalog"), "catalog あり");
ok(text.includes("/Count 2"), "ページ数 2");
ok(text.includes("/DCTDecode"), "JPEG 埋め込み");
// xref オフセットが実在の obj 位置を指すか（1 個検証）
const xrefIdx = text.indexOf("\nxref\n");
const after = text.slice(xrefIdx + 1).split("\n");
const firstOff = parseInt(after[3].slice(0, 10), 10);
ok(text.slice(firstOff, firstOff + 6) === "1 0 ob", "xref オフセットが正しい");

// --- textOf ---
ok(R.textOf(book).includes("はじめに"), "book の本文を抽出");
ok(R.textOf(music).includes("朝の光"), "music の歌詞を抽出");

// --- scriptBlocks (radio / book / その他) ---
const radio = JSON.parse(readFileSync(path.join(root, "works/moco-news-20261009.radio.json"), "utf8"));
const rb = R.scriptBlocks(radio);
ok(rb[0].kind === "title" && rb[0].text.includes("モコ"), "radio: 先頭はタイトル");
ok(rb.some(b => b.kind === "marker" && b.text.includes("お茶")), "radio: 章マーカーを保持");
const spk = rb.filter(b => b.kind === "speaker");
ok(spk.length === 5, "radio: 発話5つを話者ブロックに");
ok(spk[0].text === "モコ" && spk[0].body.includes("おかえりなさい"), "radio: 話者名と台本本文を分離");
ok(spk.every(b => b.body && b.body.length > 0), "radio: 全発話に本文がある");
ok(spk.every(b => b.dur > 0), "radio: 発話に尺がある");
const bb = R.scriptBlocks(book);
ok(bb.some(b => b.kind === "h2"), "book: 章見出しを h2 に");
ok(bb.filter(b => b.kind === "body").length > 0, "book: 本文ブロックがある");
// 未知 kind でもタイトル + 本文で落ちない
const gen = R.scriptBlocks({ kind: "music", id: "x", title: "T", lyrics: [{ lines: ["a", "b"] }] });
ok(gen[0].kind === "title" && gen.length >= 2, "その他: タイトル + 本文");
// 全 kind で例外を出さない
for (const k of ["music", "radio", "movie", "book", "article", "voice"]) {
  const b = R.scriptBlocks({ kind: k, id: "z", title: "T" });
  ok(Array.isArray(b) && b.length >= 1, `scriptBlocks(${k}) が配列を返す`);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
