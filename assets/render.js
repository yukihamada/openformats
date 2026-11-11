/* openformats メディア・レンダラ — 作品 JSON から音声/画像/動画/PDF をブラウザ内で作る。
 *
 * ブラウザでも Node でも読める。外部依存ゼロ・ファイル送信なし。
 *   OFRender.synthWav(work)   -> { bytes: Uint8Array, sampleRate, durationSec }
 *   OFRender.renderPng(work)  -> Promise<Blob>   (canvas)
 *   OFRender.renderWebm(work) -> Promise<Blob>   (canvas + MediaRecorder)
 *   OFRender.renderPdf(work)  -> Promise<Blob>   (canvas ページを JPEG で PDF に埋め込む)
 *
 * 純粋部分 (WAV エンコード・旋律生成・PDF 組み立て) は Node で単体テストする。
 * canvas / MediaRecorder を使う部分はブラウザでのみ動く。
 *
 * 正直な注記: ここで作る音声はブラウザ合成のプレビュー音源で、
 * 本物の声 (TTS) は tools/render.py の KOE レンダラ (teai API) を使う。
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.OFRender = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // ---- 決定的な擬似乱数 (content_hash から) -------------------------------
  function hashSeed(str) {
    var h = 2166136261 >>> 0;
    var s = String(str || "openformats");
    for (var i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return h >>> 0;
  }
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // ---- 作品から読むテキスト ------------------------------------------------
  function textOf(work) {
    var parts = [];
    if (work.title) parts.push(work.title);
    (work.lyrics || []).forEach(function (ly) { (ly.lines || []).forEach(function (l) { parts.push(l); }); });
    (work.segments || []).forEach(function (s) { if (s.text) parts.push(s.text); });
    if (work.kind === "book" || work.kind === "article") {
      (work.chapters || []).forEach(function (ch) {
        (ch.blocks || []).forEach(function (b) {
          if (b.text) parts.push(b.text);
          if (b.items) parts = parts.concat(b.items);
        });
      });
    }
    return parts.join("\n").trim();
  }

  // ---- 旋律生成 (純粋) ----------------------------------------------------
  // ペンタトニック。sections の energy と bars から音数・強弱を決める。
  var PENTA = [0, 2, 4, 7, 9, 12, 14, 16, 19, 21]; // 半音
  function midiToFreq(m) { return 440 * Math.pow(2, (m - 69) / 12); }

  function melodyFromWork(work) {
    var seed = hashSeed((work && (work.content_hash || work.id)) || "openformats");
    var rng = mulberry32(seed);
    var meta = (work && work.meta) || {};
    var bpm = Number(meta.bpm) || 96;
    var beatSec = 60 / bpm;
    var baseMidi = 60 + PENTA[Math.floor(rng() * PENTA.length)]; // C4 付近
    var sections = (work && work.sections) || [];
    var notes = [];
    var maxSec = 20;
    var t = 0;

    function pushNote(freq, dur, amp) { notes.push({ freq: freq, dur: dur, amp: amp }); }

    if (sections.length) {
      for (var si = 0; si < sections.length && t < maxSec; si++) {
        var sec = sections[si];
        var energy = Math.max(0.15, Math.min(1, Number(sec.energy) || 0.5));
        var bars = Math.max(1, Math.min(8, Number(sec.bars) || 4));
        var count = bars * 4;
        for (var i = 0; i < count && t < maxSec; i++) {
          var step = PENTA[Math.floor(rng() * PENTA.length)];
          var oct = rng() < 0.2 ? 12 : 0;
          var freq = midiToFreq(baseMidi + step + oct);
          var dur = beatSec * (rng() < 0.25 ? 2 : 1);
          pushNote(freq, dur, 0.22 + energy * 0.5);
          t += dur;
        }
      }
    } else {
      var n = 16;
      for (var j = 0; j < n && t < maxSec; j++) {
        var f = midiToFreq(baseMidi + PENTA[Math.floor(rng() * PENTA.length)]);
        pushNote(f, beatSec, 0.4);
        t += beatSec;
      }
    }
    return { notes: notes, durationSec: Math.min(t, maxSec), bpm: bpm };
  }

  // ---- WAV エンコード (純粋) ---------------------------------------------
  var SAMPLE_RATE = 22050;
  function synthSamples(work, sampleRate) {
    sampleRate = sampleRate || SAMPLE_RATE;
    var mel = melodyFromWork(work);
    var total = Math.ceil(mel.durationSec * sampleRate) + Math.ceil(0.3 * sampleRate);
    var buf = new Float32Array(total);
    var pos = 0;
    var twoPi = Math.PI * 2;
    mel.notes.forEach(function (nt) {
      var n = Math.ceil(nt.dur * sampleRate);
      var attack = Math.min(n, Math.floor(0.01 * sampleRate));
      var release = Math.min(n, Math.floor(0.08 * sampleRate));
      for (var i = 0; i < n && pos + i < total; i++) {
        var env = 1;
        if (i < attack) env = i / attack;
        else if (i > n - release) env = (n - i) / release;
        var tt = i / sampleRate;
        // 基音 + 弱い倍音でやわらかい音色
        var s = Math.sin(twoPi * nt.freq * tt) * 0.7
          + Math.sin(twoPi * nt.freq * 2 * tt) * 0.2
          + Math.sin(twoPi * nt.freq * 3 * tt) * 0.1;
        buf[pos + i] += s * env * nt.amp;
      }
      pos += n;
    });
    // 軽いフェードアウト
    var fade = Math.min(total, Math.floor(0.3 * sampleRate));
    for (var k = 0; k < fade; k++) buf[total - fade + k] *= (fade - k) / fade;
    return { samples: buf, sampleRate: sampleRate, durationSec: total / sampleRate };
  }

  function encodeWAV(samples, sampleRate) {
    var n = samples.length;
    var dataBytes = n * 2;
    var buf = new ArrayBuffer(44 + dataBytes);
    var dv = new DataView(buf);
    function wstr(off, s) { for (var i = 0; i < s.length; i++) dv.setUint8(off + i, s.charCodeAt(i)); }
    wstr(0, "RIFF");
    dv.setUint32(4, 36 + dataBytes, true);
    wstr(8, "WAVE");
    wstr(12, "fmt ");
    dv.setUint32(16, 16, true);
    dv.setUint16(20, 1, true);          // PCM
    dv.setUint16(22, 1, true);          // mono
    dv.setUint32(24, sampleRate, true);
    dv.setUint32(28, sampleRate * 2, true); // byte rate
    dv.setUint16(32, 2, true);          // block align
    dv.setUint16(34, 16, true);         // bits
    wstr(36, "data");
    dv.setUint32(40, dataBytes, true);
    var off = 44;
    for (var i = 0; i < n; i++) {
      var s = Math.max(-1, Math.min(1, samples[i]));
      dv.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
      off += 2;
    }
    return new Uint8Array(buf);
  }

  function synthWav(work) {
    var r = synthSamples(work, SAMPLE_RATE);
    return { bytes: encodeWAV(r.samples, r.sampleRate), sampleRate: r.sampleRate, durationSec: r.durationSec };
  }

  // ---- PDF 組み立て (純粋) ------------------------------------------------
  // JPEG 画像を 1 ページ 1 枚として PDF に埋め込む。日本語は canvas 側で描くので
  // PDF のフォント埋め込みが不要になる。
  function asciiBytes(s) {
    var a = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) a[i] = s.charCodeAt(i) & 0xff;
    return a;
  }
  function buildPdf(jpegs, pageW, pageH) {
    var chunks = [];
    var offsets = [];
    var length = 0;
    function push(bytes) { chunks.push(bytes); length += bytes.length; }
    function pushStr(s) { push(asciiBytes(s)); }
    function objStart(num) { offsets[num] = length; pushStr(num + " 0 obj\n"); }

    pushStr("%PDF-1.4\n%\xE2\xE3\xCF\xD3\n");

    var n = jpegs.length;
    var pageObjNums = [];
    for (var i = 0; i < n; i++) pageObjNums.push(3 + i * 3);

    // 1 catalog
    objStart(1);
    pushStr("<< /Type /Catalog /Pages 2 0 R >>\nendobj\n");
    // 2 pages
    objStart(2);
    var kids = pageObjNums.map(function (p) { return p + " 0 R"; }).join(" ");
    pushStr("<< /Type /Pages /Kids [" + kids + "] /Count " + n + " >>\nendobj\n");

    for (var p = 0; p < n; p++) {
      var pageNum = 3 + p * 3;
      var imgNum = 4 + p * 3;
      var contentNum = 5 + p * 3;
      var jpeg = jpegs[p];
      // page
      objStart(pageNum);
      pushStr("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 " + pageW + " " + pageH + "] " +
        "/Resources << /XObject << /Im0 " + imgNum + " 0 R >> >> /Contents " + contentNum + " 0 R >>\nendobj\n");
      // image
      objStart(imgNum);
      pushStr("<< /Type /XObject /Subtype /Image /Width " + pageW + " /Height " + pageH +
        " /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length " + jpeg.length + " >>\nstream\n");
      push(jpeg);
      pushStr("\nendstream\nendobj\n");
      // content
      var content = "q " + pageW + " 0 0 " + pageH + " 0 0 cm /Im0 Do Q";
      objStart(contentNum);
      pushStr("<< /Length " + content.length + " >>\nstream\n" + content + "\nendstream\nendobj\n");
    }

    var xrefPos = length;
    var total = 2 + n * 3 + 1; // 1..(2+n*3)
    pushStr("xref\n0 " + total + "\n");
    pushStr("0000000000 65535 f \n");
    for (var o = 1; o < total; o++) {
      var off = offsets[o] || 0;
      var pad = ("0000000000" + off).slice(-10);
      pushStr(pad + " 00000 n \n");
    }
    pushStr("trailer\n<< /Size " + total + " /Root 1 0 R >>\nstartxref\n" + xrefPos + "\n%%EOF\n");

    var out = new Uint8Array(length);
    var pos = 0;
    chunks.forEach(function (c) { out.set(c, pos); pos += c.length; });
    return out;
  }

  // ---- ブラウザ専用: canvas 描画 -----------------------------------------
  function isDom() { return typeof document !== "undefined" && !!document.createElement; }

  function makeCanvas(w, h) {
    var c = document.createElement("canvas");
    c.width = w; c.height = h;
    return c;
  }

  function drawPoster(work, canvas) {
    var ctx = canvas.getContext("2d");
    var W = canvas.width, H = canvas.height;
    var g = ctx.createLinearGradient(0, 0, W, H);
    g.addColorStop(0, "#0e1330");
    g.addColorStop(1, "#243b8f");
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    // 装飾
    var rng = mulberry32(hashSeed(work.id || "openformats"));
    ctx.globalAlpha = 0.12;
    for (var i = 0; i < 24; i++) {
      ctx.beginPath();
      ctx.arc(rng() * W, rng() * H, 20 + rng() * 120, 0, Math.PI * 2);
      ctx.fillStyle = i % 2 ? "#7aa0ff" : "#a9c0ff";
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    var pad = Math.round(W * 0.07);
    ctx.fillStyle = "#eef2ff";
    ctx.font = "600 " + Math.round(W * 0.03) + "px -apple-system,'Hiragino Sans','Noto Sans JP',sans-serif";
    ctx.fillText("openformats · " + String(work.kind || "work"), pad, pad + Math.round(W * 0.03));

    ctx.fillStyle = "#ffffff";
    var titleSize = Math.round(W * 0.075);
    ctx.font = "700 " + titleSize + "px -apple-system,'Hiragino Sans','Noto Sans JP',sans-serif";
    wrapText(ctx, String(work.title || work.id || "Untitled"), pad, pad + Math.round(H * 0.34), W - pad * 2, titleSize * 1.25);

    var names = [];
    (work.authors || []).forEach(function (a) { if (a && a.name) names.push(a.name); });
    ctx.fillStyle = "#c9d4ff";
    ctx.font = Math.round(W * 0.032) + "px -apple-system,'Hiragino Sans','Noto Sans JP',sans-serif";
    if (names.length) ctx.fillText(names.join(", "), pad, H - pad - Math.round(W * 0.06));

    if (work.content_hash) {
      ctx.fillStyle = "#8ea6ff";
      ctx.font = Math.round(W * 0.022) + "px ui-monospace,Menlo,monospace";
      ctx.fillText("sha256 " + String(work.content_hash).slice(0, 32) + "…", pad, H - pad - Math.round(W * 0.02));
    }
  }

  function wrapText(ctx, text, x, y, maxW, lineH) {
    var words = String(text).split(/(\s+)/);
    if (words.length === 1) { // 日本語などスペース無し: 1 文字ずつ
      words = String(text).split("");
    }
    var line = "", lines = [];
    for (var i = 0; i < words.length; i++) {
      var test = line + words[i];
      if (ctx.measureText(test).width > maxW && line) { lines.push(line); line = words[i]; }
      else line = test;
    }
    if (line) lines.push(line);
    for (var j = 0; j < lines.length && j < 3; j++) ctx.fillText(lines[j], x, y + j * lineH);
  }

  function canvasToJpeg(canvas) {
    return new Promise(function (resolve, reject) {
      canvas.toBlob(function (blob) {
        if (!blob) { reject(new Error("canvas.toBlob が失敗")); return; }
        blob.arrayBuffer().then(function (ab) { resolve(new Uint8Array(ab)); }, reject);
      }, "image/jpeg", 0.85);
    });
  }

  function renderPng(work) {
    if (!isDom()) return Promise.reject(new Error("canvas はブラウザ専用"));
    var c = makeCanvas(1200, 630);
    drawPoster(work, c);
    return new Promise(function (resolve, reject) {
      c.toBlob(function (b) { b ? resolve(b) : reject(new Error("PNG 生成に失敗")); }, "image/png");
    });
  }

  function renderWebm(work, seconds) {
    if (!isDom()) return Promise.reject(new Error("MediaRecorder はブラウザ専用"));
    if (typeof MediaRecorder === "undefined") return Promise.reject(new Error("このブラウザは MediaRecorder 非対応"));
    seconds = Math.max(2, Math.min(12, seconds || 6));
    var c = makeCanvas(1280, 720);
    var ctx = c.getContext("2d");
    // captureStream(0) = 手動で requestFrame する。非表示タブや背面ウィンドウでも
    // 確実にフレームを送れる（captureStream(30) は隠れるとフレームが止まり録画が空になる）。
    var stream = c.captureStream(0);
    var track = stream.getVideoTracks()[0];
    var manualFrame = track && typeof track.requestFrame === "function";
    if (!manualFrame) stream = c.captureStream(30); // フォールバック
    var mime = "video/webm;codecs=vp9";
    if (!MediaRecorder.isTypeSupported(mime)) mime = "video/webm;codecs=vp8";
    if (!MediaRecorder.isTypeSupported(mime)) mime = "video/webm";
    var rec = new MediaRecorder(stream, { mimeType: mime });
    var chunks = [];
    rec.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
    var title = String(work.title || work.id || "Untitled");
    var names = [];
    (work.authors || []).forEach(function (a) { if (a && a.name) names.push(a.name); });
    // radio は台本の「今どこ」を出す。話者・章・現在の一文が分かるようにする。
    var isRadio = work.kind === "radio" && (work.segments || []).length;
    var script = isRadio ? scriptBlocks(work).filter(function (b) { return b.kind !== "title"; }) : [];
    var totalDur = 0;
    (work.segments || []).forEach(function (s) { totalDur = Math.max(totalDur, (Number(s.start_sec) || 0) + (Number(s.duration_sec) || 0)); });
    function currentBlock(el) {
      // 経過時間を台本のタイムラインに写す (尺が無ければ均等割り)
      var n = script.length;
      if (!n) return null;
      if (totalDur > 0) {
        var t = (el / seconds) * totalDur, acc = 0;
        for (var i = 0; i < n; i++) {
          var d = Number(script[i].dur) || (totalDur / n);
          if (t < acc + d) return script[i];
          acc += d;
        }
        return script[n - 1];
      }
      return script[Math.min(n - 1, Math.floor((el / seconds) * n))];
    }
    function draw(el) {
      var p = Math.min(1, el / seconds);
      var g = ctx.createLinearGradient(0, 0, 1280, 720);
      g.addColorStop(0, "#0e1330"); g.addColorStop(1, "#243b8f");
      ctx.fillStyle = g; ctx.fillRect(0, 0, 1280, 720);
      ctx.globalAlpha = 0.15;
      ctx.fillStyle = "#7aa0ff";
      ctx.beginPath(); ctx.arc(300 + Math.sin(el) * 120, 360 + Math.cos(el * 0.8) * 120, 220, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 1;
      ctx.fillStyle = "#eef2ff";
      ctx.font = "600 28px -apple-system,'Hiragino Sans','Noto Sans JP',sans-serif";
      ctx.fillText("openformats · " + String(work.kind || "work"), 80, 100);

      if (isRadio) {
        var blk = currentBlock(el);
        ctx.fillStyle = "#ffffff";
        ctx.font = "700 56px -apple-system,'Hiragino Sans','Noto Sans JP',sans-serif";
        wrapText(ctx, title, 80, 190, 1120, 70);
        if (blk) {
          if (blk.kind === "marker") {
            ctx.fillStyle = "#7aa0ff";
            ctx.font = "700 44px -apple-system,'Hiragino Sans','Noto Sans JP',sans-serif";
            wrapText(ctx, blk.text, 80, 340, 1120, 60);
          } else if (blk.kind === "speaker") {
            ctx.fillStyle = "#6ee7a0";
            ctx.font = "700 34px -apple-system,'Hiragino Sans','Noto Sans JP',sans-serif";
            ctx.fillText(blk.text, 80, 330);
            ctx.fillStyle = "#ffffff";
            ctx.font = "600 40px -apple-system,'Hiragino Sans','Noto Sans JP',sans-serif";
            wrapText(ctx, blk.body, 80, 400, 1120, 56);
          } else {
            ctx.fillStyle = "#c9d4ff";
            ctx.font = "32px -apple-system,'Hiragino Sans','Noto Sans JP',sans-serif";
            wrapText(ctx, blk.text, 80, 360, 1120, 44);
          }
        }
      } else {
        ctx.fillStyle = "#ffffff";
        ctx.font = "700 72px -apple-system,'Hiragino Sans','Noto Sans JP',sans-serif";
        wrapText(ctx, title, 80, 340, 1120, 90);
        ctx.fillStyle = "#c9d4ff";
        ctx.font = "32px -apple-system,'Hiragino Sans','Noto Sans JP',sans-serif";
        if (names.length) ctx.fillText(names.join(", "), 80, 640);
      }
      // 進捗バー
      ctx.fillStyle = "rgba(255,255,255,.2)"; ctx.fillRect(80, 680, 1120, 6);
      ctx.fillStyle = "#7aa0ff"; ctx.fillRect(80, 680, 1120 * p, 6);
    }
    return new Promise(function (resolve, reject) {
      rec.onstop = function () {
        clearInterval(timer);
        var blob = new Blob(chunks, { type: mime.split(";")[0] });
        if (!chunks.length) { reject(new Error("録画データが空でした")); return; }
        resolve(blob);
      };
      rec.onerror = function (e) { clearInterval(timer); reject(e.error || new Error("録画エラー")); };
      // 最初のフレームを描いてから録画開始し、固定間隔で描き続ける
      // （requestAnimationFrame は非表示タブで止まるため setInterval を使う）
      draw(0);
      if (manualFrame) track.requestFrame();
      var fps = 30, tick = 0, total = Math.round(seconds * fps);
      rec.start(100);
      var timer = setInterval(function () {
        tick++;
        draw(tick / fps);
        if (manualFrame) track.requestFrame();
        if (tick >= total) { clearInterval(timer); if (rec.state !== "inactive") rec.stop(); }
      }, 1000 / fps);
    });
  }

  // ---- 作品を「台本ブロック」に分解 (純粋) --------------------------------
  // radio は話者・章・ト書きを保った台本に、book/article は章立てに、
  // それ以外はタイトル + 本文にする。PDF/字幕/動画の元になる。
  function scriptBlocks(work) {
    work = work || {};
    var blocks = [];
    var title = String(work.title || work.id || "Untitled");
    blocks.push({ kind: "title", text: title });

    if (work.kind === "radio" && (work.segments || []).length) {
      var spk = {};
      (work.speakers || []).forEach(function (s) { spk[s.id] = s.name || s.id; });
      (work.segments || []).forEach(function (seg) {
        var t = seg.type;
        if (t === "marker") {
          if (seg.label) blocks.push({ kind: "marker", text: String(seg.label) });
        } else if (t === "speech") {
          blocks.push({ kind: "speaker", text: String(spk[seg.speaker] || seg.speaker || "話者"), body: String(seg.text || ""), dur: Number(seg.duration_sec) || 0 });
        } else if (t === "music" || t === "sfx") {
          blocks.push({ kind: "meta", text: "[" + t + (seg.src ? " " + seg.src : "") + "]", dur: Number(seg.duration_sec) || 0 });
        } else if (t === "pause" || t === "silence") {
          blocks.push({ kind: "meta", text: "(間 " + (Number(seg.duration_sec) || 0) + " 秒)", dur: Number(seg.duration_sec) || 0 });
        }
      });
    } else if ((work.kind === "book" || work.kind === "article") && (work.chapters || []).length) {
      work.chapters.forEach(function (ch) {
        blocks.push({ kind: "h2", text: String(ch.title || ch.id || "章") });
        (ch.blocks || []).forEach(function (b) {
          if (b.type === "heading") blocks.push({ kind: "h2", text: String(b.text || "") });
          else if (b.type === "list") (b.items || []).forEach(function (it) { blocks.push({ kind: "body", text: "・" + it }); });
          else blocks.push({ kind: "body", text: String(b.text || "") });
        });
      });
    } else {
      textOf(work).split("\n").forEach(function (l) {
        if (l && l !== title) blocks.push({ kind: "body", text: l });
      });
    }
    return blocks;
  }

  // 各ブロック種別の描画スタイル (canvas の font 文字列と行間)。
  var PDF_STYLES = {
    title:   { font: "700 40px", color: "#111111", lh: 70, gapBefore: 0,  gapAfter: 26 },
    h2:      { font: "700 32px", color: "#111111", lh: 52, gapBefore: 18, gapAfter: 14 },
    marker:  { font: "700 28px", color: "#2b5cff", lh: 44, gapBefore: 26, gapAfter: 10 },
    speaker: { font: "700 24px", color: "#0a7d33", lh: 38, gapBefore: 16, gapAfter: 4 },
    body:    { font: "26px",     color: "#222222", lh: 40, gapBefore: 0,  gapAfter: 8 },
    meta:    { font: "italic 22px", color: "#888888", lh: 34, gapBefore: 2, gapAfter: 6 }
  };
  var PDF_FAMILY = " -apple-system,'Hiragino Sans','Noto Sans JP',sans-serif";

  function renderPdf(work) {
    if (!isDom()) return Promise.reject(new Error("canvas はブラウザ専用"));
    var W = 1240, H = 1754; // A4 相当 (150dpi)
    var pad = 100, left = pad, maxW = W - pad * 2, bottom = H - pad;
    var blocks = scriptBlocks(work);

    // まず各ブロックを「行」に展開し、ページ境界で分割する (長い台本も切れない)
    var pages = [];
    var page = [];
    var y = pad + 40;
    function newPage() { pages.push(page); page = []; y = pad + 40; }

    blocks.forEach(function (blk) {
      var st = PDF_STYLES[blk.kind] || PDF_STYLES.body;
      y += st.gapBefore || 0;
      var texts = blk.kind === "speaker" ? [blk.text, blk.body] : [blk.text];
      texts.forEach(function (raw, idx) {
        var font = idx === 0 ? st.font : "26px";
        var color = idx === 0 ? st.color : "#222222";
        var lh = idx === 0 ? st.lh : 40;
        // 行の折り返し幅はフォントに依存するので、計測用の一時 canvas を使う
        var meas = makeCanvas(8, 8).getContext("2d");
        meas.font = font + PDF_FAMILY;
        var lines = wrapLines(meas, raw || "", maxW);
        lines.forEach(function (line) {
          if (y + lh > bottom) newPage();
          page.push({ text: line, x: left, y: y, font: font + PDF_FAMILY, color: color });
          y += lh;
        });
      });
      y += st.gapAfter || 0;
    });
    if (page.length) pages.push(page);
    if (!pages.length) pages.push([]);

    // ページを canvas に描いて JPEG 化 → PDF にまとめる
    var jpegs = [];
    var chain = Promise.resolve();
    pages.forEach(function (ops, pageIndex) {
      chain = chain.then(function () {
        var c = makeCanvas(W, H);
        var ctx = c.getContext("2d");
        ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, W, H);
        ops.forEach(function (op) {
          ctx.fillStyle = op.color; ctx.font = op.font;
          ctx.fillText(op.text, op.x, op.y);
        });
        // フッタ: ページ番号 + ハッシュ
        ctx.fillStyle = "#aaaaaa"; ctx.font = "20px ui-monospace,monospace";
        ctx.fillText((pageIndex + 1) + " / " + pages.length, W - pad - 90, H - 50);
        if (work.content_hash) ctx.fillText("sha256 " + String(work.content_hash).slice(0, 24) + "…", pad, H - 50);
        return canvasToJpeg(c).then(function (jpg) { jpegs.push(jpg); });
      });
    });
    return chain.then(function () {
      var bytes = buildPdf(jpegs, W, H);
      return new Blob([bytes], { type: "application/pdf" });
    });
  }

  function wrapLines(ctx, text, maxW) {
    var chars = String(text).split("");
    var line = "", out = [];
    for (var i = 0; i < chars.length; i++) {
      var test = line + chars[i];
      if (ctx.measureText(test).width > maxW && line) { out.push(line); line = chars[i]; }
      else line = test;
    }
    if (line) out.push(line);
    return out.length ? out : [""];
  }

  return {
    hashSeed: hashSeed,
    mulberry32: mulberry32,
    textOf: textOf,
    scriptBlocks: scriptBlocks,
    melodyFromWork: melodyFromWork,
    encodeWAV: encodeWAV,
    synthSamples: synthSamples,
    synthWav: synthWav,
    buildPdf: buildPdf,
    renderPng: renderPng,
    renderWebm: renderWebm,
    renderPdf: renderPdf,
    SAMPLE_RATE: SAMPLE_RATE
  };
});
