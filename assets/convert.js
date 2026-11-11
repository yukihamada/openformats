/* openformats 変換ライブラリ — tools/export.py の忠実な移植。
 *
 * ブラウザでも Node でも動く。外部依存ゼロ。
 *   OFConvert.toSchemaOrg(work)  -> schema.org JSON-LD
 *   OFConvert.toC2PA(work)       -> C2PA マニフェスト相当 JSON
 *   OFConvert.fromSchemaOrg(ld)  -> openformats 作品 JSON (逆変換)
 *   OFConvert.contentHash(work)  -> JCS-SHA256 (hex)
 *
 * Python 版と出力が一致することを tests/convert.test.mjs で照合する。
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.OFConvert = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // ---- JCS (RFC 8785) -----------------------------------------------------
  // Python canonical.py と同じ規則。数値は ECMAScript Number::toString。
  function numToEs(x) {
    if (typeof x !== "number") throw new Error("not a number");
    if (!isFinite(x)) throw new Error("NaN/Infinity は JSON で表現できない");
    if (x === 0) return "0";
    return JSON.stringify(x);
  }

  function escapeString(s) {
    // JSON.stringify は ECMAScript の文字列エスケープに一致する。
    return JSON.stringify(s);
  }

  function keySort(a, b) {
    // UTF-16 コードユニット順 = JS の既定の文字列比較。
    return a < b ? -1 : a > b ? 1 : 0;
  }

  function canonicalize(v) {
    if (v === null) return "null";
    if (v === true) return "true";
    if (v === false) return "false";
    if (typeof v === "number") return numToEs(v);
    if (typeof v === "string") return escapeString(v);
    if (Array.isArray(v)) return "[" + v.map(canonicalize).join(",") + "]";
    if (typeof v === "object") {
      var keys = Object.keys(v).sort(keySort);
      return "{" + keys.map(function (k) {
        if (typeof k !== "string") throw new Error("key must be string");
        return escapeString(k) + ":" + canonicalize(v[k]);
      }).join(",") + "}";
    }
    throw new Error("unsupported type: " + typeof v);
  }

  // ---- SHA-256 (純 JS・同期) ---------------------------------------------
  // ブラウザでも Node でも同じ結果。外部依存ゼロ。
  var K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ];
  function utf8Bytes(str) {
    if (typeof TextEncoder !== "undefined") return new TextEncoder().encode(str);
    var out = [];
    for (var i = 0; i < str.length; i++) {
      var c = str.charCodeAt(i);
      if (c < 0x80) out.push(c);
      else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
      else if (c < 0xd800 || c >= 0xe000) out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
      else {
        i++; var c2 = str.charCodeAt(i);
        var cp = 0x10000 + (((c & 0x3ff) << 10) | (c2 & 0x3ff));
        out.push(0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 63), 0x80 | ((cp >> 6) & 63), 0x80 | (cp & 63));
      }
    }
    return new Uint8Array(out);
  }
  function rotr(x, n) { return (x >>> n) | (x << (32 - n)); }
  function sha256Bytes(bytes) {
    var H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    var len = bytes.length;
    var bitLen = len * 8;
    var withPad = new Uint8Array(Math.ceil((len + 9) / 64) * 64);
    withPad.set(bytes);
    withPad[len] = 0x80;
    // 64bit length の下位 32bit を末尾に書く (bitLen < 2^32 前提)
    withPad[withPad.length - 4] = (bitLen >>> 24) & 0xff;
    withPad[withPad.length - 3] = (bitLen >>> 16) & 0xff;
    withPad[withPad.length - 2] = (bitLen >>> 8) & 0xff;
    withPad[withPad.length - 1] = bitLen & 0xff;
    withPad[withPad.length - 8] = Math.floor(bitLen / 0x100000000) & 0xff;

    var w = new Int32Array(64);
    for (var off = 0; off < withPad.length; off += 64) {
      for (var i = 0; i < 16; i++) {
        w[i] = (withPad[off + i * 4] << 24) | (withPad[off + i * 4 + 1] << 16) | (withPad[off + i * 4 + 2] << 8) | withPad[off + i * 4 + 3];
      }
      for (i = 16; i < 64; i++) {
        var s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
        var s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
      }
      var a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
      for (i = 0; i < 64; i++) {
        var S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        var ch = (e & f) ^ (~e & g);
        var t1 = (h + S1 + ch + K[i] + w[i]) | 0;
        var S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + maj) | 0;
        h = g; g = f; f = e; e = (d + t1) | 0;
        d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      H[0] = (H[0] + a) | 0; H[1] = (H[1] + b) | 0; H[2] = (H[2] + c) | 0; H[3] = (H[3] + d) | 0;
      H[4] = (H[4] + e) | 0; H[5] = (H[5] + f) | 0; H[6] = (H[6] + g) | 0; H[7] = (H[7] + h) | 0;
    }
    var hex = "";
    for (i = 0; i < 8; i++) {
      var x = H[i] >>> 0;
      hex += ("00000000" + x.toString(16)).slice(-8);
    }
    return hex;
  }
  var _sha256 = null;
  function sha256Hex(str) {
    if (_sha256) return _sha256(str);
    return sha256Bytes(utf8Bytes(str));
  }
  function setSha256(fn) { _sha256 = fn; }

  // ---- content_hash -------------------------------------------------------
  var EXCLUDE_FROM_HASH = { content_hash: 1, signatures: 1, hash_chain: 1, renditions: 1, revisions: 1 };

  function body(data) {
    var o = {};
    Object.keys(data).forEach(function (k) {
      if (!EXCLUDE_FROM_HASH[k]) o[k] = data[k];
    });
    var prov = o.provenance;
    if (prov && typeof prov === "object" && "history" in prov) {
      var p = {};
      Object.keys(prov).forEach(function (k) { if (k !== "history") p[k] = prov[k]; });
      o.provenance = p;
    }
    var clone = o.clone;
    if (clone && typeof clone === "object" && "consent" in clone) {
      var c = {};
      Object.keys(clone).forEach(function (k) { if (k !== "consent") c[k] = clone[k]; });
      o.clone = c;
    }
    var sp = o.speaker;
    if (sp && typeof sp === "object") {
      var s = {};
      Object.keys(sp).forEach(function (k) {
        if (k !== "consent" && k !== "consent_doc") s[k] = sp[k];
      });
      if (Object.keys(s).length) o.speaker = s; else delete o.speaker;
    }
    return o;
  }

  function contentHash(data) {
    return sha256Hex(canonicalize(body(data)));
  }

  // ---- schema.org export --------------------------------------------------
  var SCHEMA_TYPE = {
    music: "MusicComposition", radio: "PodcastEpisode", book: "Book",
    movie: "Movie", voice: "AudioObject", image: "ImageObject",
    article: "Article", bim: "CreativeWork", device: "Product",
    land: "Place", country: "Place", event: "Event",
    collection: "CollectionPage", person: "Person", place: "Place",
    product: "Product"
  };

  var LICENSE_URL = {
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "MIT": "https://opensource.org/licenses/MIT"
  };

  function authors(data) {
    var out = [];
    (data.authors || []).forEach(function (a) {
      if (!a || typeof a !== "object" || !a.name) return;
      var person = { "@type": "Person", name: a.name };
      if (a.url) person.url = a.url;
      out.push(person);
    });
    return out;
  }

  function toSchemaOrg(data) {
    var kind = data.kind;
    var stype = SCHEMA_TYPE[kind] || "CreativeWork";
    var ld = {
      "@context": "https://schema.org",
      "@type": stype,
      name: data.title || data.name || data.id,
      identifier: data.id
    };
    ld.additionalType = "openformats:" + kind;
    if (data.description) ld.description = data.description;
    if (data.url) ld.url = data.url;
    if (data.lang) ld.inLanguage = data.lang;
    var au = authors(data);
    if (au.length) ld.author = au.length > 1 ? au : au[0];
    if (data.created_at) ld.dateCreated = data.created_at;
    if (data.updated_at) ld.dateModified = data.updated_at;

    var lic = data.license;
    if (LICENSE_URL[lic]) ld.license = LICENSE_URL[lic];

    if (data.content_hash) ld.sha256 = data.content_hash;

    var media = [];
    (data.renditions || []).forEach(function (r) {
      if (!r || !r.path) return;
      var mtype = r.mime || r.format;
      var enc = { "@type": "MediaObject", contentUrl: r.path };
      if (mtype) enc.encodingFormat = mtype;
      if (r.sha256) enc.sha256 = r.sha256;
      media.push(enc);
    });
    if (media.length) ld.associatedMedia = media;

    if (kind === "product") {
      if (data.group) ld.category = data.group;
      if (data.status) ld.additionalProperty = {
        "@type": "PropertyValue", name: "status", value: data.status
      };
    }
    return ld;
  }

  // ---- C2PA export --------------------------------------------------------
  var C2PA_ACTIONS = {
    create: "c2pa.created", edit: "c2pa.edited",
    migrate: "c2pa.converted", publish: "c2pa.published"
  };

  function c2paFormat(data) {
    var fmt = {
      music: "audio/mpeg", radio: "audio/mpeg", voice: "audio/mpeg",
      movie: "video/mp4", image: "image/png", book: "application/epub+zip",
      article: "text/html"
    };
    var rends = data.renditions || [];
    for (var i = 0; i < rends.length; i++) {
      if (rends[i] && rends[i].mime) return rends[i].mime;
    }
    return fmt[data.kind] || "application/json";
  }

  function toC2PA(data) {
    var prov = data.provenance || {};
    var gen = prov.generator || {};
    var claimGenerator = gen.name || "openformats";
    if (gen.version) claimGenerator += "/" + gen.version;

    var assertions = [];

    if (data.content_hash) {
      assertions.push({ label: "c2pa.hash.data", data: { alg: "sha256", hash: data.content_hash } });
    }

    var au = [];
    (data.authors || []).forEach(function (a) {
      if (a && typeof a === "object" && a.name) au.push(a.name);
    });
    if (au.length) {
      assertions.push({
        label: "stds.schema-org.CreativeWork",
        data: {
          "@context": "https://schema.org",
          "@type": "CreativeWork",
          author: au.map(function (n) { return { "@type": "Person", name: n }; }),
          name: data.title || data.id
        }
      });
    }

    var actions = [];
    (prov.history || []).forEach(function (h) {
      actions.push({
        action: C2PA_ACTIONS[h.action] || "c2pa.edited",
        when: h.at,
        softwareAgent: claimGenerator,
        digitalSourceType: (prov.human_involvement === "ai-assisted" || prov.human_involvement === "ai-generated")
          ? "trainedAlgorithmicMedia" : "digitalCapture"
      });
    });
    if (actions.length) assertions.push({ label: "c2pa.actions", data: { actions: actions } });

    var genInfo = {};
    if (gen.name) genInfo.name = gen.name;
    if (gen.version) genInfo.version = gen.version;
    if (prov.human_involvement) genInfo.human_involvement = prov.human_involvement;
    if (Object.keys(genInfo).length) {
      assertions.push({ label: "c2pa.ai_generative_training", data: genInfo });
    }

    var ingredients = [];
    (data.renditions || []).forEach(function (r) {
      if (!r || !r.sha256) return;
      var ing = { title: r.path || r.kind, hash: { alg: "sha256", hash: r.sha256 } };
      if (r.format) ing.format = r.format;
      if (r.model) ing.model = r.model;
      ingredients.push(ing);
    });

    var sigs = [];
    (data.signatures || []).forEach(function (s) {
      if (!s || s.alg !== "Ed25519") return;
      sigs.push({
        alg: "Ed25519",
        signer: s.signer === undefined ? null : s.signer,
        signed_at: s.signed_at === undefined ? null : s.signed_at,
        public_key: s.public_key === undefined ? null : s.public_key,
        signature: s.signature === undefined ? null : s.signature
      });
    });

    var manifest = {
      claim_generator: claimGenerator,
      claim_generator_info: Object.keys(genInfo).length ? genInfo : null,
      title: data.title || data.id,
      format: c2paFormat(data),
      instance_id: data.id,
      assertions: assertions,
      ingredients: ingredients,
      signature_info: sigs,
      openformats: {
        spec_version: data.spec_version,
        kind: data.kind,
        content_hash: data.content_hash
      }
    };
    // None / [] / {} を落とす
    var out = {};
    Object.keys(manifest).forEach(function (k) {
      var v = manifest[k];
      if (v === null) return;
      if (Array.isArray(v) && v.length === 0) return;
      if (v && typeof v === "object" && !Array.isArray(v) && Object.keys(v).length === 0) return;
      out[k] = v;
    });
    return out;
  }

  // ---- schema.org import (逆変換) ----------------------------------------
  var TYPE_TO_KIND = {};
  Object.keys(SCHEMA_TYPE).forEach(function (k) { TYPE_TO_KIND[SCHEMA_TYPE[k]] = k; });
  TYPE_TO_KIND.CreativeWork = "article";
  TYPE_TO_KIND.AudioObject = "voice";
  TYPE_TO_KIND.Place = "place";
  TYPE_TO_KIND.Product = "product";
  TYPE_TO_KIND.CollectionPage = "collection";

  function slugify(s) {
    s = String(s).toLowerCase().trim();
    s = s.replace(/[^a-z0-9-]+/g, "-");
    s = s.replace(/-+/g, "-").replace(/^-+|-+$/g, "");
    if (!s || !/^[a-z0-9]/.test(s)) s = "w-" + s;
    return s.slice(0, 64);
  }

  function fromSchemaOrg(ld) {
    var stype = ld["@type"];
    if (Array.isArray(stype)) stype = stype[0] || null;

    var kind = null;
    var at = ld.additionalType;
    if (typeof at === "string" && at.indexOf("openformats:") === 0) {
      var cand = at.split(":")[1];
      if (SCHEMA_TYPE[cand]) kind = cand;
    }
    if (kind === null) kind = TYPE_TO_KIND[stype] || "article";

    var wid = ld.identifier || ld.name;
    if (wid && typeof wid === "object") wid = wid.value;
    wid = wid ? slugify(wid) : "imported";

    var data = { spec_version: "1.1.0", kind: kind, id: wid };
    if (ld.name) data.title = ld.name;
    if (ld.description) data.description = ld.description;
    if (ld.inLanguage) data.lang = ld.inLanguage;
    if (ld.url) data.url = ld.url;

    var licUrl = ld.license;
    if (licUrl && typeof licUrl === "object") licUrl = licUrl.url || licUrl["@id"];
    Object.keys(LICENSE_URL).forEach(function (spdx) {
      if (LICENSE_URL[spdx] === licUrl) data.license = spdx;
    });

    var au = [];
    var raw = ld.author;
    if (raw && typeof raw === "object" && !Array.isArray(raw)) raw = [raw];
    (raw || []).forEach(function (a) {
      if (a && typeof a === "object" && a.name) {
        var person = { name: a.name };
        if (a.url) person.url = a.url;
        au.push(person);
      } else if (typeof a === "string") {
        au.push({ name: a });
      }
    });
    if (au.length) data.authors = au;

    if (ld.dateCreated) data.created_at = ld.dateCreated;
    if (ld.dateModified) data.updated_at = ld.dateModified;

    var rends = [];
    var media = ld.associatedMedia;
    if (media && typeof media === "object" && !Array.isArray(media)) media = [media];
    (media || []).forEach(function (m) {
      if (!m || typeof m !== "object") return;
      var r = {};
      if (m.contentUrl) r.path = m.contentUrl;
      if (m.encodingFormat) r.format = m.encodingFormat;
      if (m.sha256) r.sha256 = m.sha256;
      if (Object.keys(r).length) rends.push(r);
    });
    if (rends.length) data.renditions = rends;

    if (ld.sha256) data.content_hash = ld.sha256;
    else data.content_hash = contentHash(data);
    return data;
  }

  // ---- Markdown / CSV / MusicXML / OTIO -----------------------------------
  function xmlEscape(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");
  }

  function blocksToMarkdown(blocks) {
    var out = [];
    (blocks || []).forEach(function (b) {
      var t = b.type;
      if (t === "heading") {
        var lvl = Math.min(Math.max(parseInt(b.level, 10) || 2, 1), 6);
        out.push(new Array(lvl + 1).join("#") + " " + String(b.text || ""));
      } else if (t === "paragraph") {
        out.push(String(b.text || ""));
      } else if (t === "list") {
        var items = b.items || [];
        out.push(items.map(function (it, i) {
          return (b.ordered ? (i + 1) + "." : "-") + " " + String(it);
        }).join("\n"));
      } else if (t === "quote") {
        out.push("> " + String(b.text || ""));
      } else if (t === "code") {
        out.push("```" + String(b.lang || "") + "\n" + String(b.text || "") + "\n```");
      } else if (t === "table") {
        var rows = b.rows || [];
        if (rows.length) {
          function cells(r) { return "| " + r.map(String).join(" | ") + " |"; }
          out.push(cells(rows[0]));
          out.push("| " + rows[0].map(function () { return "---"; }).join(" | ") + " |");
          rows.slice(1).forEach(function (r) { out.push(cells(r)); });
        }
      } else if (t === "figure") {
        out.push("![" + String(b.alt || "") + "](" + String(b.src || "") + ")");
        var cap = b.caption || b.alt || "";
        if (cap) out.push("*" + String(cap) + "*");
      } else if (t === "divider") {
        out.push("---");
      } else if (t === "footnote") {
        out.push("[^]: " + String(b.text || ""));
      } else if (b.text) {
        out.push(String(b.text));
      }
    });
    return out.join("\n\n");
  }

  function toMarkdown(data) {
    var title = data.title || data.name || data.id || "Untitled";
    var lines = ["# " + String(title), ""];
    var meta = [];
    if (data.kind) meta.push("- 種類: " + String(data.kind));
    var names = [];
    (data.authors || []).forEach(function (a) {
      if (a && typeof a === "object" && a.name) names.push(a.name);
    });
    if (names.length) meta.push("- 作者: " + names.join(", "));
    if (data.lang) meta.push("- 言語: " + String(data.lang));
    if (data.license) meta.push("- ライセンス: " + String(data.license));
    if (data.created_at) meta.push("- 作成: " + String(data.created_at));
    if (data.content_hash) meta.push("- 指紋 (SHA-256): " + String(data.content_hash));
    if (meta.length) { lines = lines.concat(meta); lines.push(""); }

    var kind = data.kind;
    if (kind === "book" || kind === "article") {
      var chapters = data.chapters || [];
      if (chapters.length) {
        chapters.forEach(function (ch) {
          lines.push("## " + String(ch.title || ch.id || "章"));
          lines.push("");
          lines.push(blocksToMarkdown(ch.blocks));
          lines.push("");
        });
      } else {
        lines.push(blocksToMarkdown(data.blocks));
        lines.push("");
      }
    } else if (kind === "music") {
      var sections = data.sections || [];
      if (sections.length) {
        lines.push("## 構成");
        lines.push("");
        sections.forEach(function (s) {
          lines.push("- " + String(s.name || "") +
            (s.duration_sec != null ? "（" + s.duration_sec + " 秒）" : ""));
        });
        lines.push("");
      }
      var tracks = data.tracks || [];
      if (tracks.length) {
        lines.push("## トラック");
        lines.push("");
        tracks.forEach(function (t) { lines.push("- " + String(t.instrument || t.id || "track")); });
        lines.push("");
      }
      (data.lyrics || []).forEach(function (ly) {
        lines.push("## 歌詞（" + String(ly.section || "") + "）");
        lines.push("");
        (ly.lines || []).forEach(function (ln) { lines.push(String(ln)); });
        lines.push("");
      });
    } else if (kind === "movie") {
      (data.timeline || []).forEach(function (t) {
        lines.push("## " + String(t.id || t.type || "track"));
        lines.push("");
        (t.clips || []).forEach(function (c) {
          var label = c.src || c.text || "clip";
          var start = c.start_sec || 0;
          var startStr = (typeof start === "number" && start % 1 !== 0) ? String(start) : String(start) + ".0";
          var endVal = start + (c.duration_sec || 0);
          var endStr = (typeof endVal === "number" && endVal % 1 !== 0) ? String(endVal) : String(endVal) + ".0";
          lines.push("- " + startStr + "〜" + endStr + "秒: " + String(label));
        });
        lines.push("");
      });
    }
    return lines.join("\n").replace(/\s+$/, "") + "\n";
  }

  function toCSV(data) {
    var cols = ["id", "kind", "title", "authors", "lang", "license", "created_at", "content_hash", "url"];
    var names = [];
    (data.authors || []).forEach(function (a) {
      if (a && typeof a === "object" && a.name) names.push(a.name);
    });
    function cell(v) {
      var s = (v == null) ? "" : String(v);
      if (/[",\n\r]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
      return s;
    }
    var row = [data.id, data.kind, data.title || data.name,
      names.length ? names.join("; ") : "", data.lang, data.license,
      data.created_at, data.content_hash, data.url];
    return cols.map(cell).join(",") + "\n" + row.map(cell).join(",") + "\n";
  }

  var KEY_FIFTHS = {
    "C major": 0, "G major": 1, "D major": 2, "A major": 3, "E major": 4,
    "B major": 5, "F# major": 6, "C# major": 7,
    "F major": -1, "Bb major": -2, "Eb major": -3, "Ab major": -4,
    "Db major": -5, "Gb major": -6, "Cb major": -7,
    "A minor": 0, "E minor": 1, "B minor": 2, "F# minor": 3, "C# minor": 4,
    "G# minor": 5, "D# minor": 6, "A# minor": 7,
    "D minor": -1, "G minor": -2, "C minor": -3, "F minor": -4,
    "Bb minor": -5, "Eb minor": -6, "Ab minor": -7
  };
  function keyToFifths(key) {
    if (!key) return [0, "major"];
    var k = String(key).trim();
    if (Object.prototype.hasOwnProperty.call(KEY_FIFTHS, k)) {
      return [KEY_FIFTHS[k], k.indexOf("minor") >= 0 ? "minor" : "major"];
    }
    var norm = k.replace(/♯/g, "#").replace(/♭/g, "b").replace(/\s+/g, " ");
    for (var cand in KEY_FIFTHS) {
      if (cand.toLowerCase() === norm.toLowerCase()) {
        return [KEY_FIFTHS[cand], cand.indexOf("minor") >= 0 ? "minor" : "major"];
      }
    }
    return [0, "major"];
  }

  function toMusicXML(data) {
    var meta = data.meta || {};
    var title = data.title || data.id || "Untitled";
    var composer = [];
    (data.authors || []).forEach(function (a) {
      if (a && typeof a === "object" && a.name) composer.push(a.name);
    });
    composer = composer.join(", ");
    var bpm = meta.bpm || 120;
    var timeSig = meta.time_signature || "4/4";
    var beats = 4, beatType = 4;
    var m = String(timeSig).split("/");
    if (m.length === 2) {
      beats = parseInt(m[0], 10) || 4;
      beatType = parseInt(m[1], 10) || 4;
    }
    var kf = keyToFifths(meta.key || "C major");
    var fifths = kf[0], mode = kf[1];

    var sections = data.sections || [];
    var lyricsBySection = {};
    (data.lyrics || []).forEach(function (ly) {
      var s = ly.section;
      if (!lyricsBySection[s]) lyricsBySection[s] = [];
      lyricsBySection[s] = lyricsBySection[s].concat(ly.lines || []);
    });

    var tracks = data.tracks || [];
    var vocal = null;
    for (var i = 0; i < tracks.length; i++) {
      var t = tracks[i];
      if (t.role === "vocal" || String(t.instrument || "").toLowerCase().indexOf("vocal") >= 0) { vocal = t; break; }
    }
    var partName = String((vocal || tracks[0] || {}).instrument || "Melody");

    var L = [];
    L.push('<?xml version="1.0" encoding="UTF-8"?>');
    L.push('<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" ' +
      '"http://www.musicxml.org/dtds/partwise.dtd">');
    L.push('<score-partwise version="4.0">');
    L.push('  <work><work-title>' + xmlEscape(title) + '</work-title></work>');
    L.push('  <identification>');
    if (composer) L.push('    <creator type="composer">' + xmlEscape(composer) + '</creator>');
    L.push('    <encoding><software>openformats export.py</software></encoding>');
    L.push('  </identification>');
    L.push('  <part-list>');
    L.push('    <score-part id="P1"><part-name>' + xmlEscape(partName) + '</part-name></score-part>');
    L.push('  </part-list>');
    L.push('  <part id="P1">');

    if (!sections.length) sections = [{ name: "section1" }];
    sections.forEach(function (sec, idx) {
      L.push('    <measure number="' + (idx + 1) + '">');
      if (idx === 0) {
        L.push('      <attributes>');
        L.push('        <divisions>1</divisions>');
        L.push('        <key><fifths>' + fifths + '</fifths><mode>' + mode + '</mode></key>');
        L.push('        <time><beats>' + beats + '</beats><beat-type>' + beatType + '</beat-type></time>');
        L.push('        <clef><sign>G</sign><line>2</line></clef>');
        L.push('      </attributes>');
        L.push('      <direction placement="above"><direction-type>' +
          '<metronome><beat-unit>quarter</beat-unit>' +
          '<per-minute>' + Math.trunc(bpm) + '</per-minute></metronome></direction-type>' +
          '<sound tempo="' + Math.trunc(bpm) + '"/></direction>');
      }
      var secLines = lyricsBySection[sec.name] || [];
      if (secLines.length) {
        var per = Math.max(1, beats);
        var used = Math.min(per, secLines.length);
        for (var j = 0; j < used; j++) {
          L.push('      <note>');
          L.push('        <pitch><step>C</step><octave>4</octave></pitch>');
          L.push('        <duration>1</duration>');
          L.push('        <type>quarter</type>');
          L.push('        <lyric number="1"><text>' + xmlEscape(secLines[j]) + '</text></lyric>');
          L.push('      </note>');
        }
        for (var r = 0; r < per - used; r++) {
          L.push('      <note><rest/><duration>1</duration><type>quarter</type></note>');
        }
      } else {
        L.push('      <note><rest measure="yes"/><duration>' + Math.max(1, beats) + '</duration></note>');
      }
      L.push('    </measure>');
    });
    L.push('  </part>');
    L.push('</score-partwise>');
    return L.join("\n") + "\n";
  }

  function toOTIO(data) {
    var fmt = data.format || {};
    var fps = parseFloat(fmt.fps || 24);
    function rt(sec) {
      return { "OTIO_SCHEMA": "RationalTime.1", value: Math.round(parseFloat(sec || 0) * fps * 1e6) / 1e6, rate: fps };
    }
    function trange(start, dur) {
      return { "OTIO_SCHEMA": "TimeRange.1", start_time: rt(start), duration: rt(dur) };
    }
    var tracks = [];
    (data.timeline || []).forEach(function (t) {
      var ttype = t.type;
      var kind = ({ video: "Video", audio: "Audio", music: "Audio", subtitle: "Video", overlay: "Video" })[ttype] || "Video";
      var children = [];
      var cursor = 0;
      var clips = (t.clips || []).slice().sort(function (a, b) { return (a.start_sec || 0) - (b.start_sec || 0); });
      clips.forEach(function (c) {
        var start = parseFloat(c.start_sec || 0);
        var dur = parseFloat(c.duration_sec || 0);
        if (start > cursor + 1e-9) {
          children.push({ "OTIO_SCHEMA": "Gap.1", name: "gap", source_range: trange(0, start - cursor), metadata: {}, effects: [], markers: [], enabled: true });
        }
        var name = c.src || c.text || "clip";
        var media = null;
        if (c.src) {
          media = { "OTIO_SCHEMA": "ExternalReference.1", target_url: String(c.src), available_range: null, available_image_bounds: null };
        }
        var clip = {
          "OTIO_SCHEMA": "Clip.2", name: String(name).slice(0, 120),
          source_range: trange(c.in_sec || 0, dur), media_reference: media,
          metadata: {}, effects: [], markers: [], enabled: true
        };
        if (c.text) clip.metadata.openformats = { subtitle_text: c.text };
        children.push(clip);
        cursor = Math.max(cursor, start) + dur;
      });
      tracks.push({
        "OTIO_SCHEMA": "Track.1", name: t.id || ttype || "track", kind: kind,
        metadata: { openformats: { type: ttype } }, source_range: null,
        effects: [], markers: [], enabled: true, children: children
      });
    });
    var total = fmt.duration_sec;
    if (total == null) {
      total = 0;
      (data.timeline || []).forEach(function (t) {
        (t.clips || []).forEach(function (c) {
          total = Math.max(total, (c.start_sec || 0) + (c.duration_sec || 0));
        });
      });
    }
    var stack = {
      "OTIO_SCHEMA": "Stack.1", name: data.title || data.id || "timeline",
      metadata: { openformats: { id: data.id, kind: "movie" } },
      source_range: null, effects: [], markers: [], enabled: true, children: tracks
    };
    return {
      "OTIO_SCHEMA": "Timeline.1", name: data.title || data.id || "timeline",
      global_start_time: rt(0),
      metadata: { openformats: { id: data.id, content_hash: data.content_hash, fps: fps, duration_sec: total } },
      tracks: stack
    };
  }

  return {
    init: setSha256,
    sha256Hex: sha256Hex,
    canonicalize: canonicalize,
    contentHash: contentHash,
    toSchemaOrg: toSchemaOrg,
    toC2PA: toC2PA,
    toMarkdown: toMarkdown,
    toCSV: toCSV,
    toMusicXML: toMusicXML,
    toOTIO: toOTIO,
    fromSchemaOrg: fromSchemaOrg,
    slugify: slugify,
    SCHEMA_TYPE: SCHEMA_TYPE
  };
});
