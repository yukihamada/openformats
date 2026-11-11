#!/usr/bin/env python3
"""openformats validator — JSON Schema (Draft 2020-12) で作品 JSON を検証する。

使い方:
    python3 tools/validate.py music/v1.json examples/sample.music.json [more.json ...]
    python3 tools/validate.py --all          # 全サンプル・作品・カタログを kind 別に検証

$ref / $schema の https://yukihamada.github.io/openformats/... を、リポジトリ内の
実ファイルへローカル解決する (ネットワーク不要)。外部依存は jsonschema のみ。
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

from openformats.radio import semantic_errors as _semantic_errors

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIRS = ("examples", "works", "products", "events", "places")
SKIP_DIRS = {"tools", ".git", ".venv", "venv", "node_modules", "__pycache__", ".ofstore"}


def _skip(path):
    """リポジトリ内でも検証対象外のディレクトリ（.venv 等）を除外する。"""
    return any(p in SKIP_DIRS or p.startswith(".") for p in path.parts)


def build_registry():
    """$id -> ローカルファイル を registry に登録し、$ref を解決可能にする。"""
    resources = []
    for path in ROOT.rglob("*.json"):
        if _skip(path.relative_to(ROOT)):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        sid = data.get("$id")
        if sid:
            resources.append((sid, Resource.from_contents(data)))
    return Registry().with_resources(resources)


def schema_for_kind(kind: str) -> pathlib.Path:
    return ROOT / kind / "v1.json"


def iter_data_files():
    for sub in DATA_DIRS:
        d = ROOT / sub
        if d.is_dir():
            yield from sorted(d.rglob("*.json"))


def _disp(path):
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def validate_one(validator, path):
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    sem = _semantic_errors(data)
    if errors or sem:
        print(f"NG  {_disp(path)}")
        for e in errors:
            loc = "/".join(str(p) for p in e.path) or "(root)"
            print(f"    - {loc}: {e.message}")
        for loc, msg in sem:
            print(f"    - {loc}: {msg}")
        return 1
    print(f"OK  {_disp(path)}")
    return 0


def main(argv):
    registry = build_registry()

    if len(argv) >= 2 and argv[1] == "--all":
        failed = 0
        cache = {}
        for path in iter_data_files():
            data = json.loads(path.read_text(encoding="utf-8"))
            kind = data.get("kind")
            if not kind:
                print(f"NG  {_disp(path)}: kind が無い")
                failed += 1
                continue
            if kind not in cache:
                sp = schema_for_kind(kind)
                if not sp.exists():
                    print(f"NG  {_disp(path)}: schema {kind}/v1.json が無い")
                    failed += 1
                    continue
                cache[kind] = Draft202012Validator(
                    json.loads(sp.read_text(encoding="utf-8")), registry=registry)
            failed += validate_one(cache[kind], path)
        print(f"\n{'FAIL' if failed else 'PASS'}: {failed} 件の不整合")
        return 1 if failed else 0

    if len(argv) < 3:
        sys.exit(__doc__)
    schema_path = pathlib.Path(argv[1])
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=registry)

    failed = 0
    for data_path in argv[2:]:
        failed += validate_one(validator, pathlib.Path(data_path))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
