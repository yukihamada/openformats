#!/usr/bin/env python3
"""openformats export / import — 作品 JSON と既存標準の相互変換。

実装済みの変換:
    schema.org  — 各 kind を schema.org の JSON-LD へ (CreativeWork 系 / Product)
    c2pa        — 来歴・署名を C2PA マニフェスト (JSON) へ
    import      — schema.org JSON-LD から openformats 作品 JSON を復元 (逆変換)

使い方:
    python3 tools/export.py schema.org works/hitotsu-saki-e.music.json
    python3 tools/export.py c2pa       works/hitotsu-saki-e.music.json
    python3 tools/export.py import     /tmp/ld/hitotsu-saki-e.schemaorg.json
    python3 tools/export.py schema.org works/*.json --out-dir /tmp/ld
    python3 tools/export.py --list

設計: 外部依存ゼロ。content_hash を schema.org の `sha256` / C2PA の
assertion に残すので、書き出した先から元作品を照合できる。schema.org は
往復可能 (export → import で id・title・authors・content_hash が戻る)。
"""
from __future__ import annotations

import argparse
import io
import json
import pathlib
import re
import struct
import sys
import zipfile
from xml.sax.saxutils import escape as _xml_escape

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from openformats import core  # noqa: E402

# kind -> schema.org の型
SCHEMA_TYPE = {
    "music": "MusicComposition",
    "radio": "PodcastEpisode",
    "book": "Book",
    "movie": "Movie",
    "voice": "AudioObject",
    "image": "ImageObject",
    "article": "Article",
    "bim": "CreativeWork",
    "device": "Product",
    "land": "Place",
    "country": "Place",
    "event": "Event",
    "collection": "CollectionPage",
    "person": "Person",
    "place": "Place",
    "product": "Product",
}

# schema.org の license URL は CC 等のみ。all-rights-reserved は付けない。
LICENSE_URL = {
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "MIT": "https://opensource.org/licenses/MIT",
}


def _authors(data):
    out = []
    for a in data.get("authors", []) or []:
        if not isinstance(a, dict) or not a.get("name"):
            continue
        person = {"@type": "Person", "name": a["name"]}
        if a.get("url"):
            person["url"] = a["url"]
        out.append(person)
    return out


def to_schema_org(data: dict) -> dict:
    kind = data.get("kind")
    stype = SCHEMA_TYPE.get(kind, "CreativeWork")
    ld = {
        "@context": "https://schema.org",
        "@type": stype,
        "name": data.get("title") or data.get("name") or data.get("id"),
        "identifier": data.get("id"),
    }
    # schema.org の型だけでは device と product のように複数 kind が同じ型へ
    # 写るため、元の kind を additionalType に残して往復を可逆にする。
    ld["additionalType"] = f"openformats:{kind}"
    if data.get("description"):
        ld["description"] = data["description"]
    if data.get("url"):
        ld["url"] = data["url"]
    if data.get("lang"):
        ld["inLanguage"] = data["lang"]
    authors = _authors(data)
    if authors:
        ld["author"] = authors if len(authors) > 1 else authors[0]
    if data.get("created_at"):
        ld["dateCreated"] = data["created_at"]
    if data.get("updated_at"):
        ld["dateModified"] = data["updated_at"]

    lic = data.get("license")
    if lic in LICENSE_URL:
        ld["license"] = LICENSE_URL[lic]

    # content_hash を identifier の補助として残す (作品照合)
    if data.get("content_hash"):
        ld["sha256"] = data["content_hash"]

    # renditions -> associatedMedia / encoding
    rends = data.get("renditions") or []
    media = []
    for r in rends:
        path = r.get("path")
        if not path:
            continue
        mtype = r.get("mime") or r.get("format")
        enc = {"@type": "MediaObject", "contentUrl": path}
        if mtype:
            enc["encodingFormat"] = mtype
        if r.get("sha256"):
            enc["sha256"] = r["sha256"]
        media.append(enc)
    if media:
        ld["associatedMedia"] = media

    # product 固有
    if kind == "product":
        if data.get("group"):
            ld["category"] = data["group"]
        if data.get("status"):
            ld["additionalProperty"] = {
                "@type": "PropertyValue",
                "name": "status",
                "value": data["status"],
            }
    return ld


# ---------------------------------------------------------------------------
# C2PA (Content Credentials) マニフェストへの書き出し
# ---------------------------------------------------------------------------
#
# C2PA は「この作品を誰が・いつ・どう作ったか」を暗号学的に示す標準。
# openformats の content_hash / signatures / provenance / renditions は
# C2PA の claim / assertion / signature / ingredient にほぼ 1:1 で対応する。
# ここでは完全な C2PA JUMBF バイナリではなく、その中身に相当する
# マニフェスト JSON (C2PA の claim generator 情報を含む) を書き出す。
# 実バイナリ埋め込み (JUMBF/COSE) は c2pa-rs 等が必要なので対象外。

C2PA_ACTIONS = {
    "create": "c2pa.created",
    "edit": "c2pa.edited",
    "migrate": "c2pa.converted",
    "publish": "c2pa.published",
}


def to_c2pa(data: dict) -> dict:
    """作品 JSON を C2PA マニフェスト相当の JSON へ写す。"""
    prov = data.get("provenance") or {}
    gen = prov.get("generator") or {}
    claim_generator = gen.get("name") or "openformats"
    if gen.get("version"):
        claim_generator += f"/{gen['version']}"

    assertions = []

    # 1. 作品の同一性 = content_hash
    if data.get("content_hash"):
        assertions.append({
            "label": "c2pa.hash.data",
            "data": {"alg": "sha256", "hash": data["content_hash"]},
        })

    # 2. 作者・作成日時
    authors = [a.get("name") for a in (data.get("authors") or [])
               if isinstance(a, dict) and a.get("name")]
    if authors:
        assertions.append({
            "label": "stds.schema-org.CreativeWork",
            "data": {
                "@context": "https://schema.org",
                "@type": "CreativeWork",
                "author": [{"@type": "Person", "name": n} for n in authors],
                "name": data.get("title") or data.get("id"),
            },
        })

    # 3. 来歴の操作履歴 -> c2pa.actions
    actions = []
    for h in prov.get("history") or []:
        act = h.get("action")
        actions.append({
            "action": C2PA_ACTIONS.get(act, "c2pa.edited"),
            "when": h.get("at"),
            "softwareAgent": claim_generator,
            "digitalSourceType": "trainedAlgorithmicMedia"
            if prov.get("human_involvement") in ("ai-assisted", "ai-generated")
            else "digitalCapture",
        })
    if actions:
        assertions.append({"label": "c2pa.actions", "data": {"actions": actions}})

    # 4. 生成に使ったモデル・プロンプト (AI 来歴)
    gen_info = {}
    if gen.get("name"):
        gen_info["name"] = gen["name"]
    if gen.get("version"):
        gen_info["version"] = gen["version"]
    if prov.get("human_involvement"):
        gen_info["human_involvement"] = prov["human_involvement"]
    if gen_info:
        assertions.append({"label": "c2pa.ai_generative_training",
                           "data": gen_info})

    # 5. 媒体実体 (renditions) -> ingredient / ハッシュ
    ingredients = []
    for r in data.get("renditions") or []:
        if not r.get("sha256"):
            continue
        ing = {
            "title": r.get("path") or r.get("kind"),
            "hash": {"alg": "sha256", "hash": r["sha256"]},
        }
        if r.get("format"):
            ing["format"] = r["format"]
        if r.get("model"):
            ing["model"] = r["model"]
        ingredients.append(ing)

    # 6. 署名 (Ed25519) -> C2PA 署名情報
    sigs = []
    for s in data.get("signatures") or []:
        if s.get("alg") != "Ed25519":
            continue
        sigs.append({
            "alg": "Ed25519",
            "signer": s.get("signer"),
            "signed_at": s.get("signed_at"),
            "public_key": s.get("public_key"),
            "signature": s.get("signature"),
        })

    manifest = {
        "claim_generator": claim_generator,
        "claim_generator_info": gen_info or None,
        "title": data.get("title") or data.get("id"),
        "format": _c2pa_format(data),
        "instance_id": data.get("id"),
        "assertions": assertions,
        "ingredients": ingredients,
        "signature_info": sigs,
        "openformats": {
            "spec_version": data.get("spec_version"),
            "kind": data.get("kind"),
            "content_hash": data.get("content_hash"),
        },
    }
    # None を落とす
    return {k: v for k, v in manifest.items() if v not in (None, [], {})}


def _c2pa_format(data: dict) -> str:
    """kind/rendition から C2PA の format 文字列を推定する。"""
    fmt = {"music": "audio/mpeg", "radio": "audio/mpeg", "voice": "audio/mpeg",
           "movie": "video/mp4", "image": "image/png", "book": "application/epub+zip",
           "article": "text/html"}
    for r in data.get("renditions") or []:
        if r.get("mime"):
            return r["mime"]
    return fmt.get(data.get("kind"), "application/json")


# ---------------------------------------------------------------------------
# MusicXML への書き出し (music -> MusicXML 4.0)
# ---------------------------------------------------------------------------
#
# music JSON は「曲の構成・トラック・歌詞」を持つが、音符レベルの譜面は
# 持たない。そこで MusicXML へは、meta（bpm・key・time_signature）と
# sections・tracks・lyrics を「スコアの骨格」として写す。音符は各セクションを
# 1 小節の全休符（または歌詞入りリードシート）として置き、後で DAW 側が
# 肉付けできる最小の譜面にする。外部依存なしで有効な MusicXML を出す。

# キー名 -> MusicXML の fifths（調号のシャープ/フラット数）と mode
_KEY_FIFTHS = {
    "C major": 0, "G major": 1, "D major": 2, "A major": 3, "E major": 4,
    "B major": 5, "F# major": 6, "C# major": 7,
    "F major": -1, "Bb major": -2, "Eb major": -3, "Ab major": -4,
    "Db major": -5, "Gb major": -6, "Cb major": -7,
    "A minor": 0, "E minor": 1, "B minor": 2, "F# minor": 3, "C# minor": 4,
    "G# minor": 5, "D# minor": 6, "A# minor": 7,
    "D minor": -1, "G minor": -2, "C minor": -3, "F minor": -4,
    "Bb minor": -5, "Eb minor": -6, "Ab minor": -7,
}


def _key_to_fifths(key: str):
    """'F major' 等を (fifths, mode) に。未知は (0, 'major')。"""
    if not key:
        return 0, "major"
    k = key.strip()
    if k in _KEY_FIFTHS:
        mode = "minor" if "minor" in k else "major"
        return _KEY_FIFTHS[k], mode
    # 表記ゆれ（F#/Gb, 大文字小文字, 'maj'/'min'）を吸収
    norm = k.replace("♯", "#").replace("♭", "b")
    norm = re.sub(r"\s+", " ", norm)
    for cand, val in _KEY_FIFTHS.items():
        if cand.lower() == norm.lower():
            return val, ("minor" if "minor" in cand else "major")
    return 0, "major"


def _blocks_to_markdown(blocks) -> str:
    """openformats のブロック配列を Markdown へ。"""
    out = []
    for b in blocks or []:
        t = b.get("type")
        if t == "heading":
            lvl = b.get("level") or 2
            lvl = min(max(int(lvl), 1), 6)
            out.append("#" * lvl + " " + str(b.get("text", "")))
        elif t == "paragraph":
            out.append(str(b.get("text", "")))
        elif t == "list":
            items = b.get("items") or []
            buf = []
            for i, it in enumerate(items):
                mark = ("%d." % (i + 1)) if b.get("ordered") else "-"
                buf.append(mark + " " + str(it))
            out.append("\n".join(buf))
        elif t == "quote":
            out.append("> " + str(b.get("text", "")))
        elif t == "code":
            lang = b.get("lang") or ""
            out.append("```" + str(lang) + "\n" + str(b.get("text", "")) + "\n```")
        elif t == "table":
            rows = b.get("rows") or []
            if rows:
                def cells(r):
                    return "| " + " | ".join(str(c) for c in r) + " |"
                out.append(cells(rows[0]))
                out.append("| " + " | ".join("---" for _ in rows[0]) + " |")
                for r in rows[1:]:
                    out.append(cells(r))
        elif t == "figure":
            cap = b.get("caption") or b.get("alt") or ""
            out.append("![%s](%s)" % (str(b.get("alt", "")), str(b.get("src", ""))))
            if cap:
                out.append("*" + str(cap) + "*")
        elif t == "divider":
            out.append("---")
        elif t == "footnote":
            out.append("[^]: " + str(b.get("text", "")))
        elif b.get("text"):
            out.append(str(b.get("text", "")))
    return "\n\n".join(out)


def to_markdown(data: dict) -> str:
    """作品を読みやすい Markdown へ書き出す。"""
    title = data.get("title") or data.get("name") or data.get("id") or "Untitled"
    lines = ["# " + str(title), ""]
    meta = []
    if data.get("kind"):
        meta.append("- 種類: " + str(data.get("kind")))
    names = [a.get("name") for a in (data.get("authors") or [])
             if isinstance(a, dict) and a.get("name")]
    if names:
        meta.append("- 作者: " + ", ".join(names))
    if data.get("lang"):
        meta.append("- 言語: " + str(data.get("lang")))
    if data.get("license"):
        meta.append("- ライセンス: " + str(data.get("license")))
    if data.get("created_at"):
        meta.append("- 作成: " + str(data.get("created_at")))
    if data.get("content_hash"):
        meta.append("- 指紋 (SHA-256): " + str(data.get("content_hash")))
    if meta:
        lines.extend(meta)
        lines.append("")

    kind = data.get("kind")
    if kind in ("book", "article"):
        chapters = data.get("chapters") or []
        if chapters:
            for ch in chapters:
                lines.append("## " + str(ch.get("title") or ch.get("id") or "章"))
                lines.append("")
                lines.append(_blocks_to_markdown(ch.get("blocks")))
                lines.append("")
        else:
            lines.append(_blocks_to_markdown(data.get("blocks")))
            lines.append("")
    elif kind == "music":
        sections = data.get("sections") or []
        if sections:
            lines.append("## 構成")
            lines.append("")
            for s in sections:
                lines.append("- " + str(s.get("name") or "") +
                             ("（%s 秒）" % s.get("duration_sec") if s.get("duration_sec") is not None else ""))
            lines.append("")
        tracks = data.get("tracks") or []
        if tracks:
            lines.append("## トラック")
            lines.append("")
            for t in tracks:
                lines.append("- " + str(t.get("instrument") or t.get("id") or "track"))
            lines.append("")
        for ly in data.get("lyrics") or []:
            lines.append("## 歌詞（" + str(ly.get("section") or "") + "）")
            lines.append("")
            for ln in ly.get("lines") or []:
                lines.append(str(ln))
            lines.append("")
    elif kind == "movie":
        for t in data.get("timeline") or []:
            lines.append("## " + str(t.get("id") or t.get("type") or "track"))
            lines.append("")
            for c in t.get("clips") or []:
                label = c.get("src") or c.get("text") or "clip"
                lines.append("- %s〜%s秒: %s" % (c.get("start_sec", 0),
                                                 (c.get("start_sec", 0) or 0) + (c.get("duration_sec", 0) or 0),
                                                 str(label)))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def to_csv(data: dict) -> str:
    """作品のメタデータを 1 行の CSV に。表計算・Notion・Airtable 取り込み用。"""
    cols = ["id", "kind", "title", "authors", "lang", "license", "created_at", "content_hash", "url"]
    names = [a.get("name") for a in (data.get("authors") or [])
             if isinstance(a, dict) and a.get("name")]

    def cell(v):
        s = "" if v is None else str(v)
        if any(ch in s for ch in [",", '"', "\n", "\r"]):
            return '"' + s.replace('"', '""') + '"'
        return s

    row = [data.get("id"), data.get("kind"),
           data.get("title") or data.get("name"), "; ".join(names) if names else "",
           data.get("lang"), data.get("license"), data.get("created_at"),
           data.get("content_hash"), data.get("url")]
    return ",".join(cell(c) for c in cols) + "\n" + ",".join(cell(c) for c in row) + "\n"


def to_musicxml(data: dict) -> str:
    """music 作品を MusicXML 4.0 の score-partwise 文字列へ書き出す。"""
    meta = data.get("meta") or {}
    title = data.get("title") or data.get("id") or "Untitled"
    composer = ", ".join(a.get("name") for a in (data.get("authors") or [])
                         if isinstance(a, dict) and a.get("name"))
    bpm = meta.get("bpm") or 120
    time_sig = meta.get("time_signature") or "4/4"
    try:
        beats, beat_type = time_sig.split("/")
        beats, beat_type = int(beats), int(beat_type)
    except Exception:
        beats, beat_type = 4, 4
    fifths, mode = _key_to_fifths(meta.get("key") or "C major")

    sections = data.get("sections") or []
    lyrics_by_section = {}
    for ly in data.get("lyrics") or []:
        lyrics_by_section.setdefault(ly.get("section"), []).extend(ly.get("lines") or [])

    # 声（vocal）トラックを優先、無ければ先頭トラック
    tracks = data.get("tracks") or []
    vocal = next((t for t in tracks if t.get("role") == "vocal"
                  or "vocal" in str(t.get("instrument", "")).lower()), None)
    part_name = (vocal or (tracks[0] if tracks else {})).get("instrument") or "Melody"
    part_name = str(part_name)

    def esc(s):
        return _xml_escape(str(s))

    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
                 '"http://www.musicxml.org/dtds/partwise.dtd">')
    lines.append('<score-partwise version="4.0">')
    lines.append('  <work><work-title>%s</work-title></work>' % esc(title))
    lines.append('  <identification>')
    if composer:
        lines.append('    <creator type="composer">%s</creator>' % esc(composer))
    lines.append('    <encoding><software>openformats export.py</software></encoding>')
    lines.append('  </identification>')
    lines.append('  <part-list>')
    lines.append('    <score-part id="P1"><part-name>%s</part-name></score-part>' % esc(part_name))
    lines.append('  </part-list>')
    lines.append('  <part id="P1">')

    # セクションごとに 1 小節。歌詞があれば歌詞付き四分音符、無ければ全休符。
    if not sections:
        sections = [{"name": "section1"}]
    for idx, sec in enumerate(sections):
        lines.append('    <measure number="%d">' % (idx + 1))
        if idx == 0:
            lines.append('      <attributes>')
            lines.append('        <divisions>1</divisions>')
            lines.append('        <key><fifths>%d</fifths><mode>%s</mode></key>' % (fifths, mode))
            lines.append('        <time><beats>%d</beats><beat-type>%d</beat-type></time>' % (beats, beat_type))
            lines.append('        <clef><sign>G</sign><line>2</line></clef>')
            lines.append('      </attributes>')
            lines.append('      <direction placement="above"><direction-type>'
                         '<metronome><beat-unit>quarter</beat-unit>'
                         '<per-minute>%d</per-minute></metronome></direction-type>'
                         '<sound tempo="%d"/></direction>' % (int(bpm), int(bpm)))
        sec_lines = lyrics_by_section.get(sec.get("name")) or []
        if sec_lines:
            # 各歌詞行を 1 小節内の四分音符に割り当てる（簡易リードシート）
            per = max(1, beats)
            for j, text in enumerate(sec_lines[:per]):
                lines.append('      <note>')
                lines.append('        <pitch><step>C</step><octave>4</octave></pitch>')
                lines.append('        <duration>1</duration>')
                lines.append('        <type>quarter</type>')
                lines.append('        <lyric number="1"><text>%s</text></lyric>' % esc(text))
                lines.append('      </note>')
            for _ in range(per - min(per, len(sec_lines))):
                lines.append('      <note><rest/><duration>1</duration><type>quarter</type></note>')
        else:
            lines.append('      <note><rest measure="yes"/><duration>%d</duration></note>' % max(1, beats))
        lines.append('    </measure>')
    lines.append('  </part>')
    lines.append('</score-partwise>')
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# OpenTimelineIO への書き出し (movie -> OTIO JSON)
# ---------------------------------------------------------------------------
#
# OTIO の .otio は「JSON スキーマ」なので、外部ライブラリ無しでも
# 有効なファイルを生成できる。timeline（video/audio/subtitle トラック）を
# OTIO の Stack/Track/Clip 構造へ写す。時間は RationalTime(rate=fps)。


def to_otio(data: dict) -> dict:
    """movie 作品を OpenTimelineIO (OTIO JSON) へ書き出す。"""
    fmt = data.get("format") or {}
    fps = float(fmt.get("fps") or 24)

    def rt(sec):
        return {"OTIO_SCHEMA": "RationalTime.1",
                "value": round(float(sec or 0) * fps, 6), "rate": fps}

    def trange(start, dur):
        return {"OTIO_SCHEMA": "TimeRange.1",
                "start_time": rt(start), "duration": rt(dur)}

    tracks = []
    for t in data.get("timeline") or []:
        ttype = t.get("type")
        kind = {"video": "Video", "audio": "Audio", "music": "Audio",
                "subtitle": "Video", "overlay": "Video"}.get(ttype, "Video")
        children = []
        # OTIO のトラックは子を先頭から連続配置する。openformats の絶対
        # start_sec を保つため、前クリップとの間隔を Gap で埋める。
        cursor = 0.0
        for c in sorted(t.get("clips") or [], key=lambda x: x.get("start_sec", 0)):
            start = float(c.get("start_sec", 0) or 0)
            dur = float(c.get("duration_sec", 0) or 0)
            if start > cursor + 1e-9:
                children.append({
                    "OTIO_SCHEMA": "Gap.1",
                    "name": "gap",
                    "source_range": trange(0, start - cursor),
                    "metadata": {},
                    "effects": [],
                    "markers": [],
                    "enabled": True,
                })
            name = c.get("src") or c.get("text") or "clip"
            media = None
            if c.get("src"):
                media = {"OTIO_SCHEMA": "ExternalReference.1",
                         "target_url": str(c["src"]),
                         "available_range": None,
                         "available_image_bounds": None}
            clip = {
                "OTIO_SCHEMA": "Clip.2",
                "name": str(name)[:120],
                "source_range": trange(c.get("in_sec", 0), dur),
                "media_reference": media,
                "metadata": {},
                "effects": [],
                "markers": [],
                "enabled": True,
            }
            if c.get("text"):
                clip["metadata"]["openformats"] = {"subtitle_text": c["text"]}
            children.append(clip)
            cursor = max(cursor, start) + dur
        track = {
            "OTIO_SCHEMA": "Track.1",
            "name": t.get("id") or ttype or "track",
            "kind": kind,
            "metadata": {"openformats": {"type": ttype}},
            "source_range": None,
            "effects": [],
            "markers": [],
            "enabled": True,
            "children": children,
        }
        tracks.append(track)

    total = fmt.get("duration_sec")
    if total is None:
        total = max((c.get("start_sec", 0) + c.get("duration_sec", 0)
                     for t in data.get("timeline") or []
                     for c in (t.get("clips") or [])), default=0)
    stack = {
        "OTIO_SCHEMA": "Stack.1",
        "name": data.get("title") or data.get("id") or "timeline",
        "metadata": {"openformats": {"id": data.get("id"), "kind": "movie"}},
        "source_range": None,
        "effects": [],
        "markers": [],
        "enabled": True,
        "children": tracks,
    }
    return {
        "OTIO_SCHEMA": "Timeline.1",
        "name": data.get("title") or data.get("id") or "timeline",
        "global_start_time": rt(0),
        "metadata": {
            "openformats": {
                "id": data.get("id"),
                "content_hash": data.get("content_hash"),
                "fps": fps,
                "duration_sec": total,
            }
        },
        "tracks": stack,
    }


# ---------------------------------------------------------------------------
# EPUB への書き出し (book / article -> EPUB 3)
# ---------------------------------------------------------------------------
#
# EPUB は zip + XHTML なので標準ライブラリだけで生成できる。
# book は chapters を、article は blocks を 1 章として写す。


def _blocks_to_xhtml(blocks) -> str:
    """openformats のブロック配列を XHTML 断片へ。"""
    out = []
    for b in blocks or []:
        t = b.get("type")
        if t == "heading":
            lvl = b.get("level") or 2
            lvl = min(max(int(lvl), 1), 6)
            out.append("<h%d>%s</h%d>" % (lvl, _xml_escape(str(b.get("text", ""))), lvl))
        elif t == "paragraph":
            txt = str(b.get("text", ""))
            # **bold** を <strong> に
            txt = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", _xml_escape(txt))
            out.append("<p>%s</p>" % txt)
        elif t == "list":
            tag = "ol" if b.get("ordered") else "ul"
            items = "".join("<li>%s</li>" % _xml_escape(str(i)) for i in (b.get("items") or []))
            out.append("<%s>%s</%s>" % (tag, items, tag))
        elif t == "quote":
            out.append("<blockquote><p>%s</p></blockquote>" % _xml_escape(str(b.get("text", ""))))
        elif t == "code":
            out.append("<pre><code>%s</code></pre>" % _xml_escape(str(b.get("text", ""))))
        elif t == "table":
            rows = b.get("rows") or []
            html = ["<table>"]
            for ri, row in enumerate(rows):
                cell = "th" if ri == 0 else "td"
                html.append("<tr>" + "".join("<%s>%s</%s>" % (cell, _xml_escape(str(c)), cell) for c in row) + "</tr>")
            html.append("</table>")
            out.append("".join(html))
        elif t == "figure":
            cap = b.get("caption") or b.get("alt") or ""
            out.append("<figure><img src=\"%s\" alt=\"%s\"/><figcaption>%s</figcaption></figure>"
                       % (_xml_escape(str(b.get("src", ""))), _xml_escape(str(b.get("alt", ""))), _xml_escape(str(cap))))
        elif t == "divider":
            out.append("<hr/>")
        elif t == "footnote":
            out.append("<p class=\"footnote\">%s</p>" % _xml_escape(str(b.get("text", ""))))
        elif t == "heading":
            pass
        elif b.get("text"):
            out.append("<p>%s</p>" % _xml_escape(str(b.get("text", ""))))
    return "\n".join(out)


def to_epub(data: dict, out_path: pathlib.Path) -> dict:
    """book / article 作品を EPUB 3 ファイルへ書き出す。"""
    kind = data.get("kind")
    title = data.get("title") or data.get("id") or "Untitled"
    author = ", ".join(a.get("name") for a in (data.get("authors") or [])
                       if isinstance(a, dict) and a.get("name")) or "unknown"
    lang = data.get("lang") or "ja"
    book_id = data.get("id") or "openformats-work"
    uid = "urn:openformats:" + str(book_id)

    # 章の組み立て: book=chapters, article=blocks を 1 章に
    chapters = []
    if kind == "book" and data.get("chapters"):
        for ch in data["chapters"]:
            chapters.append((ch.get("title") or ch.get("id") or "章", ch.get("blocks") or []))
    elif kind == "article":
        chapters.append((title, data.get("blocks") or []))
    else:
        chapters.append((title, data.get("blocks") or data.get("chapters") or []))

    def esc(s):
        return _xml_escape(str(s))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # mimetype は無圧縮・先頭
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
                   '  <rootfiles>\n'
                   '    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>\n'
                   '  </rootfiles>\n</container>\n')

        manifest_items = []
        spine_items = []
        nav_links = []
        for i, (ch_title, blocks) in enumerate(chapters, 1):
            fname = "chapter%03d.xhtml" % i
            body = _blocks_to_xhtml(blocks)
            xhtml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                     '<!DOCTYPE html>\n'
                     '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="%s" lang="%s">\n'
                     '<head><meta charset="utf-8"/><title>%s</title></head>\n'
                     '<body>\n<section>\n<h1>%s</h1>\n%s\n</section>\n</body>\n</html>\n'
                     % (esc(lang), esc(lang), esc(ch_title), esc(ch_title), body))
            z.writestr("OEBPS/" + fname, xhtml)
            manifest_items.append('<item id="ch%03d" href="%s" media-type="application/xhtml+xml"/>' % (i, fname))
            spine_items.append('<itemref idref="ch%03d"/>' % i)
            nav_links.append('<li><a href="%s">%s</a></li>' % (fname, esc(ch_title)))

        # navigation document (EPUB3)
        nav = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<!DOCTYPE html>\n'
               '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
               'xml:lang="%s" lang="%s">\n<head><meta charset="utf-8"/><title>目次</title></head>\n'
               '<body><nav epub:type="toc" id="toc"><h1>目次</h1><ol>%s</ol></nav></body></html>\n'
               % (esc(lang), esc(lang), "".join(nav_links)))
        z.writestr("OEBPS/nav.xhtml", nav)
        manifest_items.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')

        # package document (content.opf)
        opf = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="%s">\n'
               '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
               '    <dc:identifier id="bookid">%s</dc:identifier>\n'
               '    <dc:title>%s</dc:title>\n'
               '    <dc:creator>%s</dc:creator>\n'
               '    <dc:language>%s</dc:language>\n'
               '    <meta property="dcterms:modified">%s</meta>\n'
               '  </metadata>\n'
               '  <manifest>\n    %s\n  </manifest>\n'
               '  <spine>\n    %s\n  </spine>\n</package>\n'
               % (esc(lang), esc(uid), esc(title), esc(author), esc(lang),
                  data.get("updated_at") or data.get("created_at") or "2026-01-01T00:00:00Z",
                  "\n    ".join(manifest_items), "\n    ".join(spine_items)))
        z.writestr("OEBPS/content.opf", opf)

    out_path.write_bytes(buf.getvalue())
    return {"out": str(out_path), "chapters": len(chapters), "bytes": len(buf.getvalue())}


# ---------------------------------------------------------------------------
# PDF への書き出し (book / article -> PDF)
# ---------------------------------------------------------------------------
#
# 外部ライブラリを使わず、PDF を直接組み立てる。日本語はフォント埋め込みが
# 必須なので、TrueType フォントのパスを --font で受け取り、サブセットでは
# なくフォント全体を埋め込む（ファイルは大きくなるが確実）。フォント未指定
# なら ASCII のみの簡易 PDF を出す（日本語は ? に落ちる）。


def _pdf_escape_text(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _ttf_read_tables(data: bytes):
    """TrueType のテーブルディレクトリを読む。{tag: (offset, length)}。"""
    if len(data) < 12:
        raise ValueError("font too small")
    num = struct.unpack(">H", data[4:6])[0]
    tables = {}
    for i in range(num):
        off = 12 + i * 16
        tag = data[off:off + 4].decode("latin-1")
        offset, length = struct.unpack(">II", data[off + 8:off + 16])
        tables[tag] = (offset, length)
    return tables


def _ttf_cmap_unicode_to_gid(data: bytes, tables: dict):
    """cmap を読み、unicode -> glyph id の辞書を作る (format 4 / 12)。"""
    if "cmap" not in tables:
        return {}
    base, _ = tables["cmap"]
    n = struct.unpack(">H", data[base + 2:base + 4])[0]
    best = None
    for i in range(n):
        rec = base + 4 + i * 8
        pid, eid, off = struct.unpack(">HHI", data[rec:rec + 8])
        sub = base + off
        fmt = struct.unpack(">H", data[sub:sub + 2])[0]
        if fmt in (4, 12):
            # 優先: (3,10)=format12, (3,1)=format4
            score = {12: 2, 4: 1}[fmt] + (1 if pid == 3 else 0)
            if best is None or score > best[0]:
                best = (score, fmt, sub)
    if not best:
        return {}
    _, fmt, sub = best
    mapping = {}
    if fmt == 4:
        segX2 = struct.unpack(">H", data[sub + 6:sub + 8])[0]
        seg = segX2 // 2
        endcodes = struct.unpack(">%dH" % seg, data[sub + 14:sub + 14 + segX2])
        startoff = sub + 16 + segX2
        startcodes = struct.unpack(">%dH" % seg, data[startoff:startoff + segX2])
        idoff = startoff + segX2
        ideltas = struct.unpack(">%dh" % seg, data[idoff:idoff + segX2])
        rangeoff = idoff + segX2
        rangeoffs = struct.unpack(">%dH" % seg, data[rangeoff:rangeoff + segX2])
        for s in range(seg):
            start, end = startcodes[s], endcodes[s]
            if start == 0xFFFF:
                continue
            delta, ro = ideltas[s], rangeoffs[s]
            for c in range(start, end + 1):
                if ro == 0:
                    gid = (c + delta) & 0xFFFF
                else:
                    gi = rangeoff + s * 2 + ro + (c - start) * 2
                    if gi + 2 > len(data):
                        continue
                    gid = struct.unpack(">H", data[gi:gi + 2])[0]
                    if gid:
                        gid = (gid + delta) & 0xFFFF
                if gid:
                    mapping[c] = gid
    else:  # format 12
        ngroups = struct.unpack(">I", data[sub + 12:sub + 16])[0]
        p = sub + 16
        for _ in range(ngroups):
            sc, ec, sg = struct.unpack(">III", data[p:p + 12])
            p += 12
            for c in range(sc, ec + 1):
                mapping[c] = sg + (c - sc)
    return mapping


def _ttf_width_array(data: bytes, tables: dict, gids) -> str:
    """使用グリフの幅を hmtx から読み、PDF の /W 配列文字列を作る。"""
    if "hmtx" not in tables or "hhea" not in tables or "head" not in tables:
        return ""
    hho, _ = tables["hhea"]
    nhm = struct.unpack(">H", data[hho + 34:hho + 36])[0]
    ho, _ = tables["head"]
    upem = struct.unpack(">H", data[ho + 18:ho + 20])[0] or 1000
    hmo, _ = tables["hmtx"]

    def adv(gid):
        if gid < nhm:
            return struct.unpack(">H", data[hmo + gid * 4:hmo + gid * 4 + 2])[0]
        return struct.unpack(">H", data[hmo + (nhm - 1) * 4:hmo + (nhm - 1) * 4 + 2])[0]

    scale = 1000.0 / upem
    items = [(g, int(round(adv(g) * scale))) for g in sorted(gids)]
    if not items:
        return ""
    parts = []
    i = 0
    while i < len(items):
        start = items[i][0]
        ws = [items[i][1]]
        j = i + 1
        while j < len(items) and items[j][0] == items[j - 1][0] + 1:
            ws.append(items[j][1])
            j += 1
        parts.append("%d [%s]" % (start, " ".join(str(w) for w in ws)))
        i = j
    return "/W [" + " ".join(parts) + "]"


def _build_pdf(lines, font_path=None, title="document"):
    """行リストから PDF を組み立てて bytes を返す。

    font_path があれば TrueType を Type0/CIDFontType2 (Identity-H) として
    埋め込み、ToUnicode CMap を付けて日本語を正しく描画・抽出できるようにする。
    無ければ Helvetica で ASCII を描く。
    """
    W, H = 595.28, 841.89
    margin = 56.0
    leading = 16.0
    font_size = 11.0
    max_lines_per_page = int((H - 2 * margin) / leading)

    # 行を折り返す（全角=2, 半角=1 の概算）
    wrapped = []
    for ln in lines:
        if ln == "":
            wrapped.append("")
            continue
        limit = 88  # 半角換算の1行幅
        cur, cnt = "", 0
        for ch in ln:
            w = 2 if ord(ch) > 0x2E80 else 1
            if cnt + w > limit:
                wrapped.append(cur)
                cur, cnt = ch, w
            else:
                cur += ch
                cnt += w
        if cur:
            wrapped.append(cur)
    pages = [wrapped[i:i + max_lines_per_page] for i in range(0, len(wrapped), max_lines_per_page)] or [[""]]

    objects = []

    def add(obj_bytes):
        objects.append(obj_bytes)
        return len(objects)

    cmap = {}
    if font_path:
        fdata = pathlib.Path(font_path).read_bytes()
        tables = _ttf_read_tables(fdata)
        cmap = _ttf_cmap_unicode_to_gid(fdata, tables)

    # ページ内容ストリーム（フォント埋め込み時は GID を 2byte で並べる）
    content_objs = []
    used_gids = set()
    for page_lines in pages:
        ops = ["BT", "/F1 %g Tf" % font_size, "%g TL" % leading,
               "%g %g Td" % (margin, H - margin)]
        first = True
        for ln in page_lines:
            if not first:
                ops.append("T*")
            first = False
            if font_path:
                hexstr = ""
                for ch in ln:
                    gid = cmap.get(ord(ch))
                    if gid is None:
                        gid = cmap.get(ord("?"), 0)
                    used_gids.add(gid)
                    hexstr += "%04X" % gid
                ops.append("<%s> Tj" % hexstr)
            else:
                safe = "".join(c if 32 <= ord(c) < 127 else "?" for c in ln)
                ops.append("(%s) Tj" % _pdf_escape_text(safe))
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1", "replace")
        content_objs.append(add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"))

    # フォント関連オブジェクト
    font_ref = "/F1 3 0 R"  # 既定: Helvetica (obj3)
    if font_path:
        # オブジェクト番号を先に確定: ff, cid, type0, tounicode, fontdesc の順
        ff = add(b"<< /Length %d /Length1 %d >>\nstream\n" % (len(fdata), len(fdata)) + fdata + b"\nendstream")
        cid_num = len(objects) + 1
        type0_num = cid_num + 1
        touni_num = type0_num + 1
        fd_num = touni_num + 1
        # 使用グリフの実幅 (/W) を hmtx から作る。無ければ既定 1000。
        w_array = _ttf_width_array(fdata, tables, used_gids)
        cidfont = ("<< /Type /Font /Subtype /CIDFontType2 /BaseFont /Embedded "
                   "/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
                   "/FontDescriptor %d 0 R /DW 1000 /CIDToGIDMap /Identity %s >>"
                   % (fd_num, w_array)).encode("latin-1")
        cid_id = add(cidfont)
        type0 = ("<< /Type /Font /Subtype /Type0 /BaseFont /Embedded "
                 "/Encoding /Identity-H /DescendantFonts [%d 0 R] /ToUnicode %d 0 R >>"
                 % (cid_id, touni_num)).encode("latin-1")
        type0_id = add(type0)
        # ToUnicode CMap: GID -> unicode（使った GID のみ）
        gid_to_uni = {}
        for u, g in cmap.items():
            if g in used_gids and g not in gid_to_uni:
                gid_to_uni[g] = u
        cmap_lines = [
            "/CIDInit /ProcSet findresource begin",
            "12 dict begin",
            "begincmap",
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
            "/CMapName /Adobe-Identity-UCS def",
            "/CMapType 2 def",
            "1 begincodespacerange",
            "<0000> <FFFF>",
            "endcodespacerange",
        ]
        items = sorted(gid_to_uni.items())
        for i in range(0, len(items), 100):
            chunk = items[i:i + 100]
            cmap_lines.append("%d beginbfchar" % len(chunk))
            for g, u in chunk:
                cmap_lines.append("<%04X> <%s>" % (g, ("%04X" % u)))
            cmap_lines.append("endbfchar")
        cmap_lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
        tounicode = "\n".join(cmap_lines).encode("latin-1", "replace")
        add(b"<< /Length %d >>\nstream\n" % len(tounicode) + tounicode + b"\nendstream")
        desc = ("<< /Type /FontDescriptor /FontName /Embedded /Flags 4 "
                "/FontBBox [0 -200 1000 900] /ItalicAngle 0 /Ascent 880 /Descent -120 "
                "/CapHeight 700 /StemV 80 /FontFile2 %d 0 R >>" % ff).encode("latin-1")
        add(desc)
        font_ref = "/F1 %d 0 R" % type0_id
    else:
        # Helvetica を obj3 に置く
        add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    # Pages プレースホルダ
    pages_obj_index = len(objects)
    objects.append(b"__PAGES__")

    page_ids = []
    for cid in content_objs:
        page = ("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %g %g] "
                "/Resources << /Font << %s >> >> /Contents %d 0 R >>"
                % (pages_obj_index + 1, W, H, font_ref, cid)).encode("latin-1")
        page_ids.append(add(page))

    kids = " ".join("%d 0 R" % p for p in page_ids)
    objects[pages_obj_index] = ("<< /Type /Pages /Count %d /Kids [%s] >>"
                                % (len(page_ids), kids)).encode("latin-1")
    pages_id = pages_obj_index + 1

    catalog_id = add(("<< /Type /Catalog /Pages %d 0 R >>" % pages_id).encode("latin-1"))

    out = io.BytesIO()
    out.write(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (len(objects) + 1)
    for i, obj in enumerate(objects, 1):
        offsets[i] = out.tell()
        out.write(b"%d 0 obj\n" % i)
        out.write(obj)
        out.write(b"\nendobj\n")
    xref_pos = out.tell()
    out.write(b"xref\n0 %d\n" % (len(objects) + 1))
    out.write(b"0000000000 65535 f \n")
    for i in range(1, len(objects) + 1):
        out.write(b"%010d 00000 n \n" % offsets[i])
    out.write(b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
              % (len(objects) + 1, catalog_id, xref_pos))
    return out.getvalue()


def to_pdf(data: dict, out_path: pathlib.Path, font_path=None) -> dict:
    """book / article 作品を PDF ファイルへ書き出す。"""
    kind = data.get("kind")
    title = data.get("title") or data.get("id") or "Untitled"
    author = ", ".join(a.get("name") for a in (data.get("authors") or [])
                       if isinstance(a, dict) and a.get("name"))

    lines = [title, ""]
    if author:
        lines.append(author)
    lines.append("")

    def blocks_to_lines(blocks):
        out = []
        for b in blocks or []:
            t = b.get("type")
            if t == "heading":
                out.append("")
                out.append(str(b.get("text", "")))
                out.append("")
            elif t == "paragraph":
                out.append(str(b.get("text", "")).replace("**", ""))
                out.append("")
            elif t == "list":
                for i, it in enumerate(b.get("items") or [], 1):
                    prefix = "%d. " % i if b.get("ordered") else "• "
                    out.append(prefix + str(it))
                out.append("")
            elif t == "quote":
                out.append("> " + str(b.get("text", "")))
                out.append("")
            elif t == "code":
                out.append(str(b.get("text", "")))
                out.append("")
            elif t == "table":
                for row in b.get("rows") or []:
                    out.append(" | ".join(str(c) for c in row))
                out.append("")
            elif t == "divider":
                out.append("――――――")
                out.append("")
            elif b.get("text"):
                out.append(str(b.get("text", "")))
                out.append("")
        return out

    if kind == "book" and data.get("chapters"):
        for ch in data["chapters"]:
            lines.append("")
            lines.append("■ " + str(ch.get("title") or ch.get("id") or ""))
            lines.append("")
            lines.extend(blocks_to_lines(ch.get("blocks")))
    else:
        lines.extend(blocks_to_lines(data.get("blocks") or data.get("chapters")))

    pdf_bytes = _build_pdf(lines, font_path=font_path, title=title)
    out_path.write_bytes(pdf_bytes)
    return {"out": str(out_path), "bytes": len(pdf_bytes)}


# ---------------------------------------------------------------------------
# C2PA バイナリ埋め込み (JUMBF ボックスを PNG/JPEG に注入)
# ---------------------------------------------------------------------------
#
# C2PA の実体は JUMBF (JPEG Universal Metadata Box Format) ボックス。
# PNG は "caBX" チャンク、JPEG は APP11 (0xEB) セグメントに JUMBF を入れる。
# ここでは to_c2pa() のマニフェスト JSON を JUMBF の JSON ボックスとして
# 包み、PNG/JPEG へ埋め込む。COSE 署名までは作らないが、マニフェストを
# 実ファイルに載せるところまで行う（読み出しも実装）。


def _jumbf_box(jumbf_type: bytes, payload: bytes) -> bytes:
    """JUMBF のスーパーボックス/ボックスを組み立てる。

    構造: LBox(4) + TBox(4) + [XLBox(8)] + payload。LBox=1 で 64bit 長。
    """
    if jumbf_type == b"jumb":
        # スーパーボックス: description box を含める
        desc = _jumbf_box(b"jumd", b"\x00" * 8 + b"application/c2pa\x00")
        payload = desc + payload
    total = 8 + len(payload)
    if total > 0xFFFFFFFF:
        return struct.pack(">I", 1) + jumbf_type + struct.pack(">Q", 16 + len(payload)) + payload
    return struct.pack(">I", total) + jumbf_type + payload


def c2pa_jumbf_bytes(manifest: dict) -> bytes:
    """C2PA マニフェスト JSON を JUMBF バイト列へ包む。"""
    j = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    json_box = _jumbf_box(b"json", j)
    return _jumbf_box(b"jumb", json_box)


def embed_c2pa_png(png_path: pathlib.Path, jumbf: bytes) -> pathlib.Path:
    """PNG の IHDR 直後に caBX チャンクとして JUMBF を挿入する。"""
    data = png_path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    # IHDR チャンクの終端を探す（先頭チャンクは必ず IHDR）
    pos = 8
    length = struct.unpack(">I", data[pos:pos + 4])[0]
    ctype = data[pos + 4:pos + 8]
    if ctype != b"IHDR":
        raise ValueError("PNG missing IHDR")
    ihdr_end = pos + 8 + length + 4  # len+type+data+crc
    # caBX チャンク: length + 'caBX' + jumbf + crc32
    import binascii
    crc = binascii.crc32(b"caBX" + jumbf) & 0xFFFFFFFF
    chunk = struct.pack(">I", len(jumbf)) + b"caBX" + jumbf + struct.pack(">I", crc)
    out = data[:ihdr_end] + chunk + data[ihdr_end:]
    png_path.write_bytes(out)
    return png_path


def read_c2pa_png(png_path: pathlib.Path):
    """PNG から caBX チャンクの JUMBF を読み、中の JSON を返す。"""
    data = png_path.read_bytes()
    pos = 8
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if ctype == b"caBX":
            return _extract_json_from_jumbf(body)
        pos += 8 + length + 4
    return None


def embed_c2pa_jpeg(jpeg_path: pathlib.Path, jumbf: bytes) -> pathlib.Path:
    """JPEG の SOI 直後に APP11 (0xEB) セグメントとして JUMBF を挿入する。

    C2PA は APP11 セグメントに "JP" 識別子 + ボックス長 + JUMBF を格納する。
    既存の APP11/JUMBF があれば取り除いてから挿入する。
    """
    data = jpeg_path.read_bytes()
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG file")
    body = b"JP" + struct.pack(">I", len(jumbf)) + jumbf
    if len(body) + 2 > 0xFFFF:
        raise ValueError("JUMBF too large for a single APP11 segment")
    seg = b"\xff\xeb" + struct.pack(">H", len(body) + 2) + body
    # 既存の C2PA APP11 セグメントを除去
    out = bytearray(data[:2])
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            break
        marker = data[pos + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            out += data[pos:pos + 2]
            pos += 2
            continue
        seglen = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        segbody = data[pos + 4:pos + 2 + seglen]
        is_c2pa = marker == 0xEB and segbody[:2] == b"JP"
        if not is_c2pa:
            out += data[pos:pos + 2 + seglen]
        pos += 2 + seglen
        if marker == 0xDA:  # SOS: 以降はエントロピー符号化データ
            out += data[pos:]
            break
    # SOI 直後に挿入
    result = data[:2] + seg + bytes(out[2:])
    jpeg_path.write_bytes(result)
    return jpeg_path


def read_c2pa_jpeg(jpeg_path: pathlib.Path):
    """JPEG の APP11 セグメントから C2PA JUMBF を読み、中の JSON を返す。"""
    data = jpeg_path.read_bytes()
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            break
        marker = data[pos + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        seglen = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        segbody = data[pos + 4:pos + 2 + seglen]
        if marker == 0xEB and segbody[:2] == b"JP":
            boxlen = struct.unpack(">I", segbody[2:6])[0]
            return _extract_json_from_jumbf(segbody[6:6 + boxlen])
        pos += 2 + seglen
        if marker == 0xDA:
            break
    return None


def embed_c2pa(image_path: pathlib.Path, jumbf: bytes) -> pathlib.Path:
    """拡張子/マジックで PNG か JPEG を判定して埋め込む。"""
    head = image_path.read_bytes()[:8]
    if head == b"\x89PNG\r\n\x1a\n":
        return embed_c2pa_png(image_path, jumbf)
    if head[:2] == b"\xff\xd8":
        return embed_c2pa_jpeg(image_path, jumbf)
    raise ValueError("unsupported image format (PNG/JPEG only)")


def read_c2pa(image_path: pathlib.Path):
    """PNG/JPEG のどちらでも C2PA マニフェストを読み戻す。"""
    head = image_path.read_bytes()[:8]
    if head == b"\x89PNG\r\n\x1a\n":
        return read_c2pa_png(image_path)
    if head[:2] == b"\xff\xd8":
        return read_c2pa_jpeg(image_path)
    return None


def _extract_json_from_jumbf(jumbf: bytes):
    """JUMBF スーパーボックスから json ボックスの JSON を取り出す。"""
    def walk(buf):
        i = 0
        while i + 8 <= len(buf):
            lbox = struct.unpack(">I", buf[i:i + 4])[0]
            tbox = buf[i + 4:i + 8]
            if lbox == 1:
                lbox = struct.unpack(">Q", buf[i + 8:i + 16])[0]
                body = buf[i + 16:i + lbox]
            else:
                body = buf[i + 8:i + lbox]
            if tbox == b"json":
                try:
                    return json.loads(body.decode("utf-8"))
                except Exception:
                    return None
            if tbox in (b"jumb",):
                r = walk(body)
                if r is not None:
                    return r
            if lbox < 8:
                break
            i += lbox
        return None
    return walk(jumbf)


# ---------------------------------------------------------------------------
# 逆変換: schema.org JSON-LD -> openformats 作品 JSON
# ---------------------------------------------------------------------------

# schema.org の型 -> openformats の kind (SCHEMA_TYPE の逆引き)
TYPE_TO_KIND = {v: k for k, v in SCHEMA_TYPE.items()}
# 同一の型が複数 kind に対応するので、代表を明示する
TYPE_TO_KIND.update({
    "CreativeWork": "article",
    "AudioObject": "voice",
    "Place": "place",
    "Product": "product",
    "CollectionPage": "collection",
})


def from_schema_org(ld: dict) -> dict:
    """schema.org JSON-LD から openformats 作品 JSON を復元する。

    export で書いた name / identifier / author / inLanguage / dateCreated /
    sha256 / associatedMedia を戻す。schema.org に無い創作内容 (歌詞・台本等)
    は復元できないので、id・title・authors 等の骨格だけを作る。
    """
    stype = ld.get("@type")
    if isinstance(stype, list):
        stype = stype[0] if stype else None

    # additionalType に元の kind が残っていればそれを優先する (device/product の
    # ように同じ schema.org 型へ写る kind を可逆に復元するため)。
    kind = None
    at = ld.get("additionalType")
    if isinstance(at, str) and at.startswith("openformats:"):
        candidate = at.split(":", 1)[1]
        if candidate in SCHEMA_TYPE:
            kind = candidate
    if kind is None:
        kind = TYPE_TO_KIND.get(stype, "article")

    wid = ld.get("identifier") or ld.get("name")
    if isinstance(wid, dict):  # identifier が PropertyValue のことがある
        wid = wid.get("value")
    wid = _slugify(str(wid)) if wid else "imported"

    data = {
        "spec_version": "1.1.0",
        "kind": kind,
        "id": wid,
    }
    if ld.get("name"):
        data["title"] = ld["name"]
    if ld.get("description"):
        data["description"] = ld["description"]
    if ld.get("inLanguage"):
        data["lang"] = ld["inLanguage"]
    if ld.get("url"):
        data["url"] = ld["url"]

    # license URL -> SPDX
    lic_url = ld.get("license")
    if isinstance(lic_url, dict):
        lic_url = lic_url.get("url") or lic_url.get("@id")
    for spdx, url in LICENSE_URL.items():
        if lic_url == url:
            data["license"] = spdx
            break

    # author
    authors = []
    raw = ld.get("author")
    if isinstance(raw, dict):
        raw = [raw]
    for a in raw or []:
        if isinstance(a, dict) and a.get("name"):
            person = {"name": a["name"]}
            if a.get("url"):
                person["url"] = a["url"]
            authors.append(person)
        elif isinstance(a, str):
            authors.append({"name": a})
    if authors:
        data["authors"] = authors

    if ld.get("dateCreated"):
        data["created_at"] = ld["dateCreated"]
    if ld.get("dateModified"):
        data["updated_at"] = ld["dateModified"]

    # associatedMedia -> renditions (path と sha256 のみ)
    rends = []
    media = ld.get("associatedMedia")
    if isinstance(media, dict):
        media = [media]
    for m in media or []:
        if not isinstance(m, dict):
            continue
        r = {}
        if m.get("contentUrl"):
            r["path"] = m["contentUrl"]
        if m.get("encodingFormat"):
            r["format"] = m["encodingFormat"]
        if m.get("sha256"):
            r["sha256"] = m["sha256"]
        if r:
            rends.append(r)
    if rends:
        data["renditions"] = rends

    # content_hash を戻す。無ければ再計算する。
    if ld.get("sha256"):
        data["content_hash"] = ld["sha256"]
    else:
        data["content_hash"] = core.content_hash(data)
    return data


def _slugify(s: str) -> str:
    """id 制約 ^[a-z0-9][a-z0-9-]{0,63}$ に合わせる。"""
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s or not s[0].isalnum():
        s = "w-" + s
    return s[:64]


def cmd_export(args):
    paths = [pathlib.Path(p) for p in args.files]
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for p in paths:
        data = core.load(p)
        ld = to_schema_org(data)
        if out_dir:
            dst = out_dir / (p.stem + ".schemaorg.json")
            dst.write_text(json.dumps(ld, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            results.append({"file": str(p), "out": str(dst), "type": ld["@type"]})
        else:
            results.append({"file": str(p), "type": ld["@type"], "jsonld": ld})
    print(json.dumps(results if len(results) != 1 else results[0], ensure_ascii=False, indent=2))


def cmd_export_c2pa(args):
    paths = [pathlib.Path(p) for p in args.files]
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for p in paths:
        data = core.load(p)
        man = to_c2pa(data)
        if out_dir:
            dst = out_dir / (p.stem + ".c2pa.json")
            dst.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            results.append({"file": str(p), "out": str(dst),
                            "assertions": len(man.get("assertions", []))})
        else:
            results.append({"file": str(p), "manifest": man})
    print(json.dumps(results if len(results) != 1 else results[0], ensure_ascii=False, indent=2))


def cmd_import(args):
    paths = [pathlib.Path(p) for p in args.files]
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for p in paths:
        ld = json.loads(p.read_text(encoding="utf-8"))
        # @graph 配列にも対応
        if isinstance(ld, dict) and isinstance(ld.get("@graph"), list) and ld["@graph"]:
            ld = ld["@graph"][0]
        data = from_schema_org(ld)
        if out_dir:
            dst = out_dir / (data["id"] + "." + data["kind"] + ".json")
            dst.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            results.append({"file": str(p), "out": str(dst), "kind": data["kind"], "id": data["id"]})
        else:
            results.append({"file": str(p), "kind": data["kind"], "work": data})
    print(json.dumps(results if len(results) != 1 else results[0], ensure_ascii=False, indent=2))


def cmd_export_markdown(args):
    paths = [pathlib.Path(p) for p in args.files]
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for p in paths:
        data = core.load(p)
        md = to_markdown(data)
        if out_dir:
            dst = out_dir / (re.sub(r"\.(book|article|music|movie|radio|voice)$", "", p.stem) + ".md")
            dst.write_text(md, encoding="utf-8")
            results.append({"file": str(p), "out": str(dst), "bytes": len(md.encode("utf-8"))})
        else:
            results.append({"file": str(p), "markdown": md})
    print(json.dumps(results if len(results) != 1 else results[0], ensure_ascii=False, indent=2))


def cmd_export_csv(args):
    paths = [pathlib.Path(p) for p in args.files]
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for p in paths:
        data = core.load(p)
        csv = to_csv(data)
        if out_dir:
            dst = out_dir / (re.sub(r"\.(book|article|music|movie|radio|voice)$", "", p.stem) + ".csv")
            dst.write_text(csv, encoding="utf-8")
            results.append({"file": str(p), "out": str(dst), "bytes": len(csv.encode("utf-8"))})
        else:
            results.append({"file": str(p), "csv": csv})
    print(json.dumps(results if len(results) != 1 else results[0], ensure_ascii=False, indent=2))


def cmd_export_musicxml(args):
    paths = [pathlib.Path(p) for p in args.files]
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for p in paths:
        data = core.load(p)
        if data.get("kind") != "music":
            results.append({"file": str(p), "error": "music 作品ではありません"})
            continue
        xml = to_musicxml(data)
        if out_dir:
            dst = out_dir / (p.stem.replace(".music", "") + ".musicxml")
            dst.write_text(xml, encoding="utf-8")
            results.append({"file": str(p), "out": str(dst), "bytes": len(xml.encode("utf-8"))})
        else:
            results.append({"file": str(p), "musicxml": xml})
    print(json.dumps(results if len(results) != 1 else results[0], ensure_ascii=False, indent=2))


def cmd_export_otio(args):
    paths = [pathlib.Path(p) for p in args.files]
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for p in paths:
        data = core.load(p)
        if data.get("kind") != "movie":
            results.append({"file": str(p), "error": "movie 作品ではありません"})
            continue
        otio = to_otio(data)
        if out_dir:
            dst = out_dir / (p.stem.replace(".movie", "") + ".otio")
            dst.write_text(json.dumps(otio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            results.append({"file": str(p), "out": str(dst),
                            "tracks": len(otio["tracks"]["children"])})
        else:
            results.append({"file": str(p), "otio": otio})
    print(json.dumps(results if len(results) != 1 else results[0], ensure_ascii=False, indent=2))


def cmd_export_epub(args):
    paths = [pathlib.Path(p) for p in args.files]
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for p in paths:
        data = core.load(p)
        if data.get("kind") not in ("book", "article"):
            results.append({"file": str(p), "error": "book / article 作品ではありません"})
            continue
        stem = re.sub(r"\.(book|article)$", "", p.stem)
        dst = (out_dir / (stem + ".epub")) if out_dir else (p.with_suffix(".epub"))
        results.append({"file": str(p), **to_epub(data, dst)})
    print(json.dumps(results if len(results) != 1 else results[0], ensure_ascii=False, indent=2))


def cmd_export_pdf(args):
    paths = [pathlib.Path(p) for p in args.files]
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for p in paths:
        data = core.load(p)
        if data.get("kind") not in ("book", "article"):
            results.append({"file": str(p), "error": "book / article 作品ではありません"})
            continue
        stem = re.sub(r"\.(book|article)$", "", p.stem)
        dst = (out_dir / (stem + ".pdf")) if out_dir else (p.with_suffix(".pdf"))
        results.append({"file": str(p), **to_pdf(data, dst, font_path=args.font)})
    print(json.dumps(results if len(results) != 1 else results[0], ensure_ascii=False, indent=2))


def cmd_embed_c2pa(args):
    """作品 JSON の C2PA マニフェストを PNG/JPEG へ埋め込む。"""
    data = core.load(pathlib.Path(args.work))
    image = pathlib.Path(args.image)
    man = to_c2pa(data)
    jumbf = c2pa_jumbf_bytes(man)
    embed_c2pa(image, jumbf)
    # 読み戻して確認
    back = read_c2pa(image)
    print(json.dumps({
        "image": str(image),
        "embedded_bytes": len(jumbf),
        "readback_ok": back is not None,
        "readback_title": (back or {}).get("title"),
    }, ensure_ascii=False, indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="export", description="openformats 作品を既存標準へ書き出す / 逆変換する")
    ap.add_argument("--list", action="store_true", help="実装済みの変換先を一覧")
    sub = ap.add_subparsers(dest="target")
    p = sub.add_parser("schema.org", help="schema.org JSON-LD へ書き出す")
    p.add_argument("files", nargs="+")
    p.add_argument("--out-dir")
    p.set_defaults(fn=cmd_export)
    c = sub.add_parser("c2pa", help="C2PA マニフェスト (JSON) へ書き出す")
    c.add_argument("files", nargs="+")
    c.add_argument("--out-dir")
    c.set_defaults(fn=cmd_export_c2pa)
    i = sub.add_parser("import", help="schema.org JSON-LD から作品 JSON を復元する")
    i.add_argument("files", nargs="+")
    i.add_argument("--out-dir")
    i.set_defaults(fn=cmd_import)
    m = sub.add_parser("musicxml", help="music 作品を MusicXML へ書き出す")
    m.add_argument("files", nargs="+")
    m.add_argument("--out-dir")
    m.set_defaults(fn=cmd_export_musicxml)
    mk = sub.add_parser("markdown", help="作品を Markdown へ書き出す")
    mk.add_argument("files", nargs="+")
    mk.add_argument("--out-dir")
    mk.set_defaults(fn=cmd_export_markdown)
    cs = sub.add_parser("csv", help="作品メタデータを CSV へ書き出す")
    cs.add_argument("files", nargs="+")
    cs.add_argument("--out-dir")
    cs.set_defaults(fn=cmd_export_csv)
    o = sub.add_parser("otio", help="movie 作品を OpenTimelineIO (OTIO JSON) へ書き出す")
    o.add_argument("files", nargs="+")
    o.add_argument("--out-dir")
    o.set_defaults(fn=cmd_export_otio)
    e = sub.add_parser("epub", help="book / article 作品を EPUB 3 へ書き出す")
    e.add_argument("files", nargs="+")
    e.add_argument("--out-dir")
    e.set_defaults(fn=cmd_export_epub)
    d = sub.add_parser("pdf", help="book / article 作品を PDF へ書き出す")
    d.add_argument("files", nargs="+")
    d.add_argument("--out-dir")
    d.add_argument("--font", help="日本語 TrueType フォントのパス（埋め込み用）")
    d.set_defaults(fn=cmd_export_pdf)
    b = sub.add_parser("embed-c2pa", help="C2PA マニフェストを PNG に埋め込む")
    b.add_argument("work", help="作品 JSON")
    b.add_argument("image", help="埋め込み先の PNG")
    b.set_defaults(fn=cmd_embed_c2pa)
    args = ap.parse_args(argv)
    if args.list or not getattr(args, "fn", None):
        print(json.dumps({
            "implemented": ["schema.org", "c2pa", "import(schema.org)",
                            "musicxml", "otio", "epub", "pdf", "markdown", "csv", "embed-c2pa"],
            "planned": [],
        }, ensure_ascii=False, indent=2))
        return 0
    return args.fn(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
