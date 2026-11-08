#!/usr/bin/env python3
"""openformats hash — content_hash を計算する。

使い方:
    python3 tools/hash.py <data.json> [--write]

--write を付けると content_hash フィールドを更新して保存する。
ハッシュ対象は content_hash / hash_chain / signatures を除いた本体の
正規化 JSON (キー整列・区切り固定・UTF-8)。
"""
import json
import sys
import hashlib
import pathlib

EXCLUDE = {"content_hash", "hash_chain", "signatures"}


def canonical_hash(data: dict) -> str:
    body = {k: v for k, v in data.items() if k not in EXCLUDE}
    norm = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    path = pathlib.Path(argv[1])
    data = json.loads(path.read_text(encoding="utf-8"))
    h = canonical_hash(data)
    if "--write" in argv:
        data["content_hash"] = h
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {h} -> {path}")
    else:
        print(h)


if __name__ == "__main__":
    main(sys.argv)
