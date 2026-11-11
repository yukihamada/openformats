/* openformats ブラウザ検証ライブラリ — tools/of.py verify の忠実な移植。
 *
 * ブラウザでも Node でも動く。外部依存ゼロ。
 *   OFVerify.verifyWork(work, filesByName) -> Promise<result>
 *     work          : 作品 JSON（object）
 *     filesByName   : { "相対パス or ファイル名": ArrayBuffer|Uint8Array }
 *
 * 検証する内容（of.py verify と同じ観点）:
 *   - content_hash: 保存値と再計算値の一致
 *   - renditions[]: 実体ファイルの SHA-256 一致
 *   - signatures[]: Ed25519 署名（content_hash 対象）
 *   - hash_chain:   末尾が現在の content_hash と一致・重複なし
 *   - revisions[]:  最終リビジョンの復元が本体と一致
 *   - envelope:     必須項目・id 形式・kind 列挙（簡易構造チェック）
 *
 * 署名検証は WebCrypto(Ed25519) があれば使い、無ければ純 JS で行う。
 */
(function (root, factory) {
  var api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  root.OFVerify = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  // convert.js の JCS/SHA-256/contentHash を再利用（無ければ自前）
  var OFC = root.OFConvert;
  if (!OFC && typeof require === "function") {
    try { OFC = require("./convert.js"); } catch (e) { OFC = null; }
  }

  function canonicalize(v) {
    if (OFC) return OFC.canonicalize(v);
    throw new Error("OFConvert が必要です");
  }

  // ---- SHA-256 (sync, bytes) ---------------------------------------------
  var K256 = [
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
  ];
  function rotr(x, n) { return (x >>> n) | (x << (32 - n)); }
  function sha256Bytes(bytes) {
    var h = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    var l = bytes.length;
    var withOne = l + 1;
    var padLen = ((withOne + 8 + 63) & ~63);
    var buf = new Uint8Array(padLen);
    buf.set(bytes);
    buf[l] = 0x80;
    var bitLenHi = Math.floor(l / 0x20000000);
    var bitLenLo = (l << 3) >>> 0;
    var dv = new DataView(buf.buffer);
    dv.setUint32(padLen - 8, bitLenHi);
    dv.setUint32(padLen - 4, bitLenLo);
    var w = new Uint32Array(64);
    for (var off = 0; off < padLen; off += 64) {
      for (var i = 0; i < 16; i++) w[i] = dv.getUint32(off + i * 4);
      for (i = 16; i < 64; i++) {
        var s0 = rotr(w[i-15],7) ^ rotr(w[i-15],18) ^ (w[i-15] >>> 3);
        var s1 = rotr(w[i-2],17) ^ rotr(w[i-2],19) ^ (w[i-2] >>> 10);
        w[i] = (w[i-16] + s0 + w[i-7] + s1) >>> 0;
      }
      var a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],hh=h[7];
      for (i = 0; i < 64; i++) {
        var S1 = rotr(e,6) ^ rotr(e,11) ^ rotr(e,25);
        var ch = (e & f) ^ (~e & g);
        var t1 = (hh + S1 + ch + K256[i] + w[i]) >>> 0;
        var S0 = rotr(a,2) ^ rotr(a,13) ^ rotr(a,22);
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + maj) >>> 0;
        hh=g; g=f; f=e; e=(d+t1)>>>0; d=c; c=b; b=a; a=(t1+t2)>>>0;
      }
      h[0]=(h[0]+a)>>>0; h[1]=(h[1]+b)>>>0; h[2]=(h[2]+c)>>>0; h[3]=(h[3]+d)>>>0;
      h[4]=(h[4]+e)>>>0; h[5]=(h[5]+f)>>>0; h[6]=(h[6]+g)>>>0; h[7]=(h[7]+hh)>>>0;
    }
    var out = new Uint8Array(32);
    var odv = new DataView(out.buffer);
    for (i = 0; i < 8; i++) odv.setUint32(i * 4, h[i]);
    return out;
  }
  function toHex(bytes) {
    var s = "";
    for (var i = 0; i < bytes.length; i++) s += bytes[i].toString(16).padStart(2, "0");
    return s;
  }
  function utf8(str) {
    if (typeof TextEncoder !== "undefined") return new TextEncoder().encode(str);
    var out = [];
    for (var i = 0; i < str.length; i++) {
      var c = str.charCodeAt(i);
      if (c < 0x80) out.push(c);
      else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
      else out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    }
    return new Uint8Array(out);
  }
  function sha256HexBytes(bytes) { return toHex(sha256Bytes(bytes)); }
  function sha256HexStr(str) { return sha256HexBytes(utf8(str)); }

  // ---- content_hash（core.py の _body と同じ除外規則） --------------------
  var EXCLUDE = { content_hash: 1, signatures: 1, hash_chain: 1, renditions: 1, revisions: 1 };
  function body(data) {
    var o = {};
    Object.keys(data).forEach(function (k) { if (!EXCLUDE[k]) o[k] = data[k]; });
    var prov = o.provenance;
    if (prov && typeof prov === "object" && "history" in prov) {
      var p = {}; Object.keys(prov).forEach(function (k) { if (k !== "history") p[k] = prov[k]; });
      o.provenance = p;
    }
    var clone = o.clone;
    if (clone && typeof clone === "object" && "consent" in clone) {
      var c = {}; Object.keys(clone).forEach(function (k) { if (k !== "consent") c[k] = clone[k]; });
      o.clone = c;
    }
    var sp = o.speaker;
    if (sp && typeof sp === "object") {
      var s = {}; Object.keys(sp).forEach(function (k) { if (k !== "consent" && k !== "consent_doc") s[k] = sp[k]; });
      if (Object.keys(s).length) o.speaker = s; else delete o.speaker;
    }
    return o;
  }
  function contentHash(data) {
    if (OFC) return OFC.contentHash(data);
    return sha256HexStr(canonicalize(body(data)));
  }

  // ---- Ed25519 (pure JS, 拡張座標) ---------------------------------------
  var P = (1n << 255n) - 19n;
  var Q = (1n << 252n) + 27742317777372353535851937790883648493n;
  function mod(a, m) { var r = a % m; return r >= 0n ? r : r + m; }
  function powMod(base, exp, m) {
    base = mod(base, m); var r = 1n;
    while (exp > 0n) { if (exp & 1n) r = (r * base) % m; base = (base * base) % m; exp >>= 1n; }
    return r;
  }
  function inv(x) { return powMod(x, P - 2n, P); }
  var D = mod(-121665n * inv(121666n), P);
  var D2 = mod(2n * D, P);
  var I = powMod(2n, (P - 1n) / 4n, P);
  function xrecover(y) {
    var xx = mod((y * y - 1n) * inv(mod(D * y * y + 1n, P)), P);
    var x = powMod(xx, (P + 3n) / 8n, P);
    if (mod(x * x - xx, P) !== 0n) x = mod(x * I, P);
    if (mod(x, 2n) !== 0n) x = P - x;
    return x;
  }
  var By = mod(4n * inv(5n), P);
  var Bx = xrecover(By);
  var BASE = [Bx, By, 1n, mod(Bx * By, P)]; // [X,Y,Z,T]

  function pointAdd(p1, p2) {
    var X1=p1[0],Y1=p1[1],Z1=p1[2],T1=p1[3];
    var X2=p2[0],Y2=p2[1],Z2=p2[2],T2=p2[3];
    var A = mod((Y1 - X1) * (Y2 - X2), P);
    var B = mod((Y1 + X1) * (Y2 + X2), P);
    var C = mod(T1 * D2 * T2, P);
    var Dd = mod(Z1 * 2n * Z2, P);
    var E = mod(B - A, P), F = mod(Dd - C, P), G = mod(Dd + C, P), H = mod(B + A, P);
    return [mod(E * F, P), mod(G * H, P), mod(F * G, P), mod(E * H, P)];
  }
  function pointDouble(p1) {
    var X1=p1[0],Y1=p1[1],Z1=p1[2];
    var A = mod(X1 * X1, P);
    var B = mod(Y1 * Y1, P);
    var C = mod(2n * Z1 * Z1, P);
    var Dd = mod(-A, P);
    var E = mod((X1 + Y1) * (X1 + Y1) - A - B, P);
    var G = mod(Dd + B, P);
    var F = mod(G - C, P);
    var H = mod(Dd - B, P);
    return [mod(E * F, P), mod(G * H, P), mod(F * G, P), mod(E * H, P)];
  }
  function scalarMult(pt, e) {
    var r = [0n, 1n, 1n, 0n];
    var base = pt;
    while (e > 0n) {
      if (e & 1n) r = pointAdd(r, base);
      base = pointDouble(base);
      e >>= 1n;
    }
    return r;
  }
  function encodePoint(pt) {
    var Zi = inv(pt[2]);
    var x = mod(pt[0] * Zi, P);
    var y = mod(pt[1] * Zi, P);
    var bits = y | ((x & 1n) << 255n);
    var out = new Uint8Array(32);
    var v = bits;
    for (var i = 0; i < 32; i++) { out[i] = Number(v & 0xffn); v >>= 8n; }
    return out;
  }
  function isOnCurve(x, y) {
    return mod(-x * x + y * y - 1n - D * x * x * y * y, P) === 0n;
  }
  function decodePoint(bytes) {
    var v = 0n;
    for (var i = 31; i >= 0; i--) v = (v << 8n) | BigInt(bytes[i]);
    var sign = (v >> 255n) & 1n;
    var y = v & ((1n << 255n) - 1n);
    var x = xrecover(y);
    if ((x & 1n) !== sign) x = P - x;
    if (!isOnCurve(x, y)) throw new Error("点が曲線上にない");
    return [x, y, 1n, mod(x * y, P)];
  }
  function bytesToBig(bytes) { var v = 0n; for (var i = bytes.length - 1; i >= 0; i--) v = (v << 8n) | BigInt(bytes[i]); return v; }
  function sha512(bytes) {
    // WebCrypto の SHA-512 は非同期のため、同期検証用に純 JS 実装を持つ。
    return sha512Bytes(bytes);
  }
  // ---- SHA-512 (sync) -----------------------------------------------------
  var K512 = [
    0x428a2f98d728ae22n,0x7137449123ef65cdn,0xb5c0fbcfec4d3b2fn,0xe9b5dba58189dbbcn,
    0x3956c25bf348b538n,0x59f111f1b605d019n,0x923f82a4af194f9bn,0xab1c5ed5da6d8118n,
    0xd807aa98a3030242n,0x12835b0145706fben,0x243185be4ee4b28cn,0x550c7dc3d5ffb4e2n,
    0x72be5d74f27b896fn,0x80deb1fe3b1696b1n,0x9bdc06a725c71235n,0xc19bf174cf692694n,
    0xe49b69c19ef14ad2n,0xefbe4786384f25e3n,0x0fc19dc68b8cd5b5n,0x240ca1cc77ac9c65n,
    0x2de92c6f592b0275n,0x4a7484aa6ea6e483n,0x5cb0a9dcbd41fbd4n,0x76f988da831153b5n,
    0x983e5152ee66dfabn,0xa831c66d2db43210n,0xb00327c898fb213fn,0xbf597fc7beef0ee4n,
    0xc6e00bf33da88fc2n,0xd5a79147930aa725n,0x06ca6351e003826fn,0x142929670a0e6e70n,
    0x27b70a8546d22ffcn,0x2e1b21385c26c926n,0x4d2c6dfc5ac42aedn,0x53380d139d95b3dfn,
    0x650a73548baf63den,0x766a0abb3c77b2a8n,0x81c2c92e47edaee6n,0x92722c851482353bn,
    0xa2bfe8a14cf10364n,0xa81a664bbc423001n,0xc24b8b70d0f89791n,0xc76c51a30654be30n,
    0xd192e819d6ef5218n,0xd69906245565a910n,0xf40e35855771202an,0x106aa07032bbd1b8n,
    0x19a4c116b8d2d0c8n,0x1e376c085141ab53n,0x2748774cdf8eeb99n,0x34b0bcb5e19b48a8n,
    0x391c0cb3c5c95a63n,0x4ed8aa4ae3418acbn,0x5b9cca4f7763e373n,0x682e6ff3d6b2b8a3n,
    0x748f82ee5defb2fcn,0x78a5636f43172f60n,0x84c87814a1f0ab72n,0x8cc702081a6439ecn,
    0x90befffa23631e28n,0xa4506cebde82bde9n,0xbef9a3f7b2c67915n,0xc67178f2e372532bn,
    0xca273eceea26619cn,0xd186b8c721c0c207n,0xeada7dd6cde0eb1en,0xf57d4f7fee6ed178n,
    0x06f067aa72176fban,0x0a637dc5a2c898a6n,0x113f9804bef90daen,0x1b710b35131c471bn,
    0x28db77f523047d84n,0x32caab7b40c72493n,0x3c9ebe0a15c9bebcn,0x431d67c49c100d4cn,
    0x4cc5d4becb3e42b6n,0x597f299cfc657e2an,0x5fcb6fab3ad6faecn,0x6c44198c4a475817n
  ];
  function rotr64(x, n) { return ((x >> n) | (x << (64n - n))) & 0xffffffffffffffffn; }
  function sha512Bytes(bytes) {
    var h = [0x6a09e667f3bcc908n,0xbb67ae8584caa73bn,0x3c6ef372fe94f82bn,0xa54ff53a5f1d36f1n,
             0x510e527fade682d1n,0x9b05688c2b3e6c1fn,0x1f83d9abfb41bd6bn,0x5be0cd19137e2179n];
    var l = bytes.length;
    var padLen = ((l + 1 + 16 + 127) & ~127);
    var buf = new Uint8Array(padLen);
    buf.set(bytes); buf[l] = 0x80;
    var bitLen = BigInt(l) * 8n;
    for (var i = 0; i < 16; i++) { buf[padLen - 1 - i] = Number((bitLen >> BigInt(8 * i)) & 0xffn); }
    var w = new Array(80);
    for (var off = 0; off < padLen; off += 128) {
      for (i = 0; i < 16; i++) {
        var v = 0n;
        for (var j = 0; j < 8; j++) v = (v << 8n) | BigInt(buf[off + i * 8 + j]);
        w[i] = v;
      }
      for (i = 16; i < 80; i++) {
        var s0 = rotr64(w[i-15],1n) ^ rotr64(w[i-15],8n) ^ (w[i-15] >> 7n);
        var s1 = rotr64(w[i-2],19n) ^ rotr64(w[i-2],61n) ^ (w[i-2] >> 6n);
        w[i] = (w[i-16] + s0 + w[i-7] + s1) & 0xffffffffffffffffn;
      }
      var a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],hh=h[7];
      for (i = 0; i < 80; i++) {
        var S1 = rotr64(e,14n) ^ rotr64(e,18n) ^ rotr64(e,41n);
        var ch = (e & f) ^ (~e & g);
        var t1 = (hh + S1 + ch + K512[i] + w[i]) & 0xffffffffffffffffn;
        var S0 = rotr64(a,28n) ^ rotr64(a,34n) ^ rotr64(a,39n);
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + maj) & 0xffffffffffffffffn;
        hh=g; g=f; f=e; e=(d+t1)&0xffffffffffffffffn; d=c; c=b; b=a; a=(t1+t2)&0xffffffffffffffffn;
      }
      h[0]=(h[0]+a)&0xffffffffffffffffn; h[1]=(h[1]+b)&0xffffffffffffffffn;
      h[2]=(h[2]+c)&0xffffffffffffffffn; h[3]=(h[3]+d)&0xffffffffffffffffn;
      h[4]=(h[4]+e)&0xffffffffffffffffn; h[5]=(h[5]+f)&0xffffffffffffffffn;
      h[6]=(h[6]+g)&0xffffffffffffffffn; h[7]=(h[7]+hh)&0xffffffffffffffffn;
    }
    var out = new Uint8Array(64);
    for (i = 0; i < 8; i++) {
      var hv = h[i];
      for (var k = 7; k >= 0; k--) { out[i * 8 + k] = Number(hv & 0xffn); hv >>= 8n; }
    }
    return out;
  }
  function hint(m) { return bytesToBig(sha512(m)); }
  function verifyEd25519(pub, msg, sig) {
    if (sig.length !== 64 || pub.length !== 32) return false;
    var R, A;
    try { R = decodePoint(sig.slice(0, 32)); A = decodePoint(pub); } catch (e) { return false; }
    var S = bytesToBig(sig.slice(32, 64));
    if (S >= Q) return false;
    var h = hint(concatBytes(sig.slice(0, 32), pub, msg)) % Q;
    var left = scalarMult(BASE, S);
    var right = pointAdd(R, scalarMult(A, h));
    return toHex(encodePoint(left)) === toHex(encodePoint(right));
  }
  function concatBytes() {
    var total = 0, i;
    for (i = 0; i < arguments.length; i++) total += arguments[i].length;
    var out = new Uint8Array(total), off = 0;
    for (i = 0; i < arguments.length; i++) { out.set(arguments[i], off); off += arguments[i].length; }
    return out;
  }
  function b64ToBytes(s) {
    var bin = (typeof atob === "function") ? atob(s) : Buffer.from(s, "base64").toString("binary");
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  // ---- JSON Patch (RFC 6902) apply ---------------------------------------
  function parsePtr(p) {
    if (p === "") return [];
    return p.slice(1).split("/").map(function (t) { return t.replace(/~1/g, "/").replace(/~0/g, "~"); });
  }
  function ptrGet(doc, toks) {
    var cur = doc;
    for (var i = 0; i < toks.length; i++) {
      if (Array.isArray(cur)) cur = cur[parseInt(toks[i], 10)];
      else if (cur && typeof cur === "object") cur = cur[toks[i]];
      else return undefined;
    }
    return cur;
  }
  function applyPatch(doc, patch) {
    var d = JSON.parse(JSON.stringify(doc));
    (patch || []).forEach(function (op) {
      var toks = parsePtr(op.path);
      var last = toks[toks.length - 1];
      var parent = toks.length ? ptrGet(d, toks.slice(0, -1)) : null;
      if (op.op === "add") {
        if (Array.isArray(parent)) parent.splice(last === "-" ? parent.length : parseInt(last, 10), 0, op.value);
        else parent[last] = op.value;
      } else if (op.op === "remove") {
        if (Array.isArray(parent)) parent.splice(parseInt(last, 10), 1);
        else delete parent[last];
      } else if (op.op === "replace") {
        if (Array.isArray(parent)) parent[parseInt(last, 10)] = op.value;
        else parent[last] = op.value;
      } else if (op.op === "move") {
        var from = ptrGet(d, parsePtr(op.from));
        var ftoks = parsePtr(op.from), flast = ftoks[ftoks.length - 1];
        var fparent = ptrGet(d, ftoks.slice(0, -1));
        if (Array.isArray(fparent)) fparent.splice(parseInt(flast, 10), 1); else delete fparent[flast];
        if (Array.isArray(parent)) parent.splice(last === "-" ? parent.length : parseInt(last, 10), 0, from);
        else parent[last] = from;
      } else if (op.op === "copy") {
        var val = ptrGet(d, parsePtr(op.from));
        if (Array.isArray(parent)) parent.splice(last === "-" ? parent.length : parseInt(last, 10), 0, JSON.parse(JSON.stringify(val)));
        else parent[last] = JSON.parse(JSON.stringify(val));
      } else if (op.op === "test") {
        if (JSON.stringify(ptrGet(d, toks)) !== JSON.stringify(op.value)) throw new Error("test 失敗: " + op.path);
      }
    });
    return d;
  }
  function reconstruct(revs, upto) {
    var b = JSON.parse(JSON.stringify(revs[0].snapshot));
    for (var i = 1; i <= upto; i++) b = applyPatch(b, revs[i].patch || []);
    return b;
  }
  function deepEqual(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

  // ---- 検証本体 -----------------------------------------------------------
  function verifyChain(data, curHash) {
    var chain = data.hash_chain || [];
    var problems = [];
    if (chain.length && chain[chain.length - 1].sha256 !== curHash) {
      problems.push("チェーン末尾 " + String(chain[chain.length - 1].sha256).slice(0, 12) +
        " が現在の content_hash " + curHash.slice(0, 12) + " と不一致");
    }
    var seen = {};
    chain.forEach(function (e) {
      var s = e.sha256;
      if (seen[s]) problems.push("重複したチェーン要素 " + String(s).slice(0, 12));
      seen[s] = 1;
    });
    return { ok: problems.length === 0, length: chain.length, problems: problems };
  }
  function verifyRevisions(data) {
    var revs = data.revisions || [];
    if (!revs.length) return { ok: true, length: 0, problems: [] };
    var problems = [];
    var restored;
    try { restored = reconstruct(revs, revs.length - 1); }
    catch (e) { return { ok: false, length: revs.length, problems: ["最終リビジョンを復元できない: " + e.message] }; }
    if (!deepEqual(restored, body(data))) problems.push("最終リビジョンの復元内容が現在の本体と不一致");
    var recorded = revs[revs.length - 1].content_hash;
    if (recorded && recorded !== contentHash(data)) problems.push("最終リビジョンの記録ハッシュが現在の content_hash と不一致");
    return { ok: problems.length === 0, length: revs.length, problems: problems };
  }
  function verifyEnvelope(data) {
    var problems = [];
    ["spec_version", "kind", "id"].forEach(function (k) { if (!data[k]) problems.push(k + " が無い"); });
    var KINDS = ["book","device","radio","movie","music","land","country","image","voice","article","event","bim","collection","person","place","product"];
    if (data.kind && KINDS.indexOf(data.kind) < 0) problems.push("kind が列挙に無い: " + data.kind);
    if (data.id && !/^[a-z0-9][a-z0-9-]{0,63}$/.test(data.id)) problems.push("id の形式が不正: " + data.id);
    if (data.spec_version && !/^1\.[0-9]+\.[0-9]+$/.test(data.spec_version)) problems.push("spec_version の形式が不正");
    return { ok: problems.length === 0, problems: problems };
  }

  function toBytes(v) {
    if (!v) return null;
    if (v instanceof Uint8Array) return v;
    if (v instanceof ArrayBuffer) return new Uint8Array(v);
    if (ArrayBuffer.isView(v)) return new Uint8Array(v.buffer, v.byteOffset, v.byteLength);
    return null;
  }
  function basename(p) { return String(p || "").split(/[\\/]/).pop(); }

  // filesByName の照合: 完全一致 → basename 一致 の順で探す
  function findFile(filesByName, relPath) {
    if (!filesByName) return null;
    if (filesByName[relPath]) return filesByName[relPath];
    var base = basename(relPath);
    var keys = Object.keys(filesByName);
    for (var i = 0; i < keys.length; i++) {
      if (basename(keys[i]) === base) return filesByName[keys[i]];
    }
    return null;
  }

  function verifyWork(work, filesByName) {
    return new Promise(function (resolve) {
      var result = { work: work.id, checks: [], ok: true };
      function add(id, label, status, detail) {
        result.checks.push({ id: id, label: label, status: status, detail: detail || "" });
        if (status === "err") result.ok = false;
      }

      // envelope
      var env = verifyEnvelope(work);
      add("envelope", "基本構造（必須項目・id・kind）", env.ok ? "ok" : "err",
        env.ok ? "spec_version / kind / id が揃っています" : env.problems.join(" / "));

      // content_hash
      var cur = contentHash(work);
      var stored = work.content_hash;
      result.content_hash_computed = cur;
      result.content_hash_stored = stored || null;
      if (!stored) {
        add("content_hash", "content_hash（作品の指紋）", "warn",
          "未設定です。of.py hash --write で計算・書き込みできます。");
      } else if (stored === cur) {
        add("content_hash", "content_hash（作品の指紋）", "ok",
          "保存値と再計算値が一致: " + cur.slice(0, 16) + "…");
      } else {
        add("content_hash", "content_hash（作品の指紋）", "err",
          "不一致。保存=" + stored.slice(0, 16) + "… / 再計算=" + cur.slice(0, 16) + "…（内容が編集され revise されていない可能性）");
      }

      // renditions
      var rends = work.renditions || [];
      if (!rends.length) {
        add("renditions", "本体ファイル（renditions）", "info", "本体ファイルを持たない作品です（renditions 空）。");
      } else {
        var pending = rends.length, anyErr = false, anyMissing = false, lines = [];
        rends.forEach(function (r) {
          var rel = r.path;
          var want = r.sha256;
          var bytes = findFile(filesByName, rel);
          if (!bytes) {
            anyMissing = true;
            lines.push("未読込: " + rel + "（ファイルを一緒にドロップしてください）");
            if (--pending === 0) finishRend();
            return;
          }
          var b = toBytes(bytes);
          var got = sha256HexBytes(b);
          if (got === want) { lines.push("一致: " + rel); }
          else { anyErr = true; lines.push("不一致: " + rel + "（期待 " + String(want).slice(0, 12) + "… / 実際 " + got.slice(0, 12) + "…）"); }
          if (--pending === 0) finishRend();
        });
        function finishRend() {
          var status = anyErr ? "err" : (anyMissing ? "warn" : "ok");
          add("renditions", "本体ファイル（renditions）", status, lines.join(" / "));
          finish();
        }
        return; // 非同期ではなく同期計算なので finishRend 内で finish
      }
      finish();

      function finish() {
        // signatures
        var sigs = work.signatures || [];
        if (!sigs.length) {
          add("signatures", "署名（Ed25519）", "info", "署名はありません（補助署名は任意）。");
        } else {
          sigs.forEach(function (s, i) {
            if (s.public_key) {
              var okSig = false;
              try { okSig = verifyEd25519(b64ToBytes(s.public_key), hexToBytes(cur), b64ToBytes(s.signature)); }
              catch (e) { okSig = false; }
              add("signatures", "署名 " + (i + 1) + (s.signer ? "（" + s.signer + "）" : ""),
                okSig ? "ok" : "err", okSig ? "content_hash に対する署名が有効です" : "署名が無効です（改ざんか鍵違い）");
            } else if (s.pubkey) {
              add("signatures", "署名 " + (i + 1) + "（bim.house）", "info",
                "bim.house 署名は content_hash と別 basis のため、この検証の対象外です。");
            } else {
              add("signatures", "署名 " + (i + 1), "err", "public_key も pubkey も無い");
            }
          });
        }

        // hash_chain
        var chain = verifyChain(work, cur);
        add("hash_chain", "履歴チェーン（hash_chain）", chain.ok ? "ok" : "err",
          chain.length ? (chain.ok ? chain.length + " 件の履歴が連続しています" : chain.problems.join(" / ")) : "履歴チェーンはありません（初版）。");

        // revisions
        var revs = verifyRevisions(work);
        add("revisions", "版の差分（revisions）", revs.ok ? "ok" : "err",
          revs.length ? (revs.ok ? revs.length + " 版の差分が本体と一致しています" : revs.problems.join(" / ")) : "差分履歴はありません。");

        // 総合
        result.ok = result.checks.every(function (c) { return c.status !== "err"; });
        resolve(result);
      }
    });
  }

  function hexToBytes(hex) {
    var out = new Uint8Array(hex.length / 2);
    for (var i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
    return out;
  }

  return {
    verifyWork: verifyWork,
    contentHash: contentHash,
    sha256HexBytes: sha256HexBytes,
    sha256HexStr: sha256HexStr,
    verifyEd25519: verifyEd25519,
    canonicalize: canonicalize
  };
});
