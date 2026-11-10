#!/usr/bin/env python3
"""openformats export — 作品 JSON を既存標準へ書き出す。

現時点で実装済みの変換:
    schema.org  — 各 kind を schema.org の JSON-LD へ (CreativeWork 系 / Product)

使い方:
    python3 tools/export.py schema.org works/hitotsu-saki-e.music.json
    python3 tools/export.py schema.org works/*.json --out-dir /tmp/ld
    python3 tools/export.py --list

設計: 外部依存ゼロ。作品 JSON を読み、kind に応じて schema.org の型へ写す。
content_hash を `identifier` に入れるので、書き出した JSON-LD から元作品を
照合できる。変換は一方向 (openformats -> schema.org) で、逆変換は未実装。
"""
from __future__ import annotations

import argparse
import json
import pathlib
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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="export", description="openformats 作品を既存標準へ書き出す")
    ap.add_argument("--list", action="store_true", help="実装済みの変換先を一覧")
    sub = ap.add_subparsers(dest="target")
    p = sub.add_parser("schema.org", help="schema.org JSON-LD へ書き出す")
    p.add_argument("files", nargs="+")
    p.add_argument("--out-dir")
    p.set_defaults(fn=cmd_export)
    args = ap.parse_args(argv)
    if args.list or not getattr(args, "fn", None):
        print(json.dumps({"implemented": ["schema.org"], "planned": ["C2PA", "MusicXML", "OpenTimelineIO", "EPUB"]}, ensure_ascii=False, indent=2))
        return 0
    return args.fn(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
