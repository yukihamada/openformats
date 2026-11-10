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
import json
import pathlib
import re
import sys

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
    args = ap.parse_args(argv)
    if args.list or not getattr(args, "fn", None):
        print(json.dumps({
            "implemented": ["schema.org", "c2pa", "import(schema.org)"],
            "planned": ["MusicXML", "OpenTimelineIO", "EPUB"],
        }, ensure_ascii=False, indent=2))
        return 0
    return args.fn(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
