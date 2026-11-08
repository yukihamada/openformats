#!/usr/bin/env python3
"""openformats validator — JSON Schema (Draft 2020-12) で作品 JSON を検証する。

使い方:
    python3 tools/validate.py <schema.json> <data.json> [more-data.json ...]

$ref は同一リポジトリ内の相対解決 ($id の https://openformats.dev/... を
ローカルファイルへマップ) に対応。外部依存は jsonschema のみ。
"""
import json
import sys
import pathlib

try:
    import jsonschema
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
except ImportError:
    sys.exit("jsonschema が必要です: pip install jsonschema")

ROOT = pathlib.Path(__file__).resolve().parent.parent


def build_registry():
    """$id -> ローカルファイル を registry に登録し、$ref を解決可能にする。"""
    resources = []
    for path in ROOT.rglob("*.json"):
        if "examples" in path.parts or "tools" in path.parts:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        sid = data.get("$id")
        if sid:
            resources.append((sid, Resource.from_contents(data)))
    return Registry().with_resources(resources)


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    schema_path = pathlib.Path(argv[1])
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    registry = build_registry()
    validator = Draft202012Validator(schema, registry=registry)

    failed = 0
    for data_path in argv[2:]:
        data = json.loads(pathlib.Path(data_path).read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
        if errors:
            failed += 1
            print(f"NG  {data_path}")
            for e in errors:
                loc = "/".join(str(p) for p in e.path) or "(root)"
                print(f"    - {loc}: {e.message}")
        else:
            print(f"OK  {data_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
