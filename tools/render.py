#!/usr/bin/env python3
"""openformats render — JSON を媒体にし、ハッシュ保存し、作品に紐づける。

概念:
    1 作品 = 1 JSON (正本)。アプリ/モデルで媒体化 (rendition) する。
    媒体は実体の SHA-256 で content-addressed ストアに保存する。
    作品本体の content_hash は変えない。だから良いモデルが出たら
    新 rendition を足すだけで「同じ作品のまま声だけ差し替え」できる。

使い方:
    # ドライラン (外部 API を呼ばず、無音/ダミーを生成して流れを確認)
    python3 tools/render.py examples/sample.music.json --kind audio --format wav --dry-run

    # 実レンダラを使う (レンダラは tools/renderers/<name>.py に置く)
    python3 tools/render.py work.json --renderer koe --kind audio --format mp3 \
        --model koe-v2 --voice yuki

    # 新しいモデルで作り直し (rendition 追加、content_hash 不変)
    python3 tools/render.py work.json --renderer koe --kind audio --format mp3 \
        --model koe-v3 --migrate-from <prev-rendition-sha256>

ストア:
    .ofstore/<sha256> — 媒体ファイル実体 (内容アドレス)。.gitignore 済み。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
import shutil
import struct
import sys
import wave

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from openformats import core  # noqa: E402
from openformats import store as storemod  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
STORE = ROOT / ".ofstore"


def _dry_wav(path: pathlib.Path, seconds: float = 1.0, rate: int = 16000):
    """無音 WAV を生成する。外部依存なしのドライラン用。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))


def _load_renderer(name: str):
    p = ROOT / "tools" / "renderers" / f"{name}.py"
    if not p.exists():
        raise SystemExit(f"レンダラ {name} が無い: {p}")
    spec = importlib.util.spec_from_file_location(f"renderer_{name}", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _store_put(src: pathlib.Path) -> dict:
    """内容定義チャンクで content-addressed ストアに置く。

    変わっていないチャンクは再利用されるので、再レンダリングしても
    実際に新規保存されるのは差分だけ (実質バイナリ差分)。
    """
    st = storemod.Store(str(STORE))
    return st.put_file_chunked(str(src))


def main(argv):
    ap = argparse.ArgumentParser(description="JSON を媒体化して作品に紐づける")
    ap.add_argument("work", help="作品 JSON")
    ap.add_argument("--kind", required=True, help="media 種別 (audio/video/image/pdf 等)")
    ap.add_argument("--format", required=True, help="ファイル形式 (wav/mp3/mp4/png 等)")
    ap.add_argument("--renderer", default=None, help="tools/renderers/<name>.py")
    ap.add_argument("--model", default=None, help="生成モデル名")
    ap.add_argument("--model-version", default=None)
    ap.add_argument("--provider", default=None)
    ap.add_argument("--voice", default=None)
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--migrate-from", default=None,
                    help="派生元 rendition の sha256 (声だけ差し替えの系譜)")
    ap.add_argument("--dry-run", action="store_true", help="外部 API を呼ばない")
    ap.add_argument("--out", default=None, help="媒体の作業出力先 (既定: 一時)")
    ap.add_argument("--write", action="store_true", help="作品 JSON を更新保存する")
    args = ap.parse_args(argv[1:])

    work_path = pathlib.Path(args.work)
    data = core.load(str(work_path))

    tmpdir = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "openformats-render"
    tmpdir.mkdir(parents=True, exist_ok=True)
    out = pathlib.Path(args.out) if args.out else tmpdir / f"{data['id']}.{args.format}"

    if args.dry_run or not args.renderer:
        if args.format != "wav":
            raise SystemExit("ドライランは --format wav のみ対応")
        _dry_wav(out)
        model = args.model or "dry-run"
        provider = args.provider or "openformats-dryrun"
    else:
        renderer = _load_renderer(args.renderer)
        if not hasattr(renderer, "render"):
            raise SystemExit(f"レンダラ {args.renderer} に render() が無い")
        model = args.model or getattr(renderer, "DEFAULT_MODEL", args.renderer)
        provider = args.provider or getattr(renderer, "PROVIDER", args.renderer)
        renderer.render(data, out, kind=args.kind, format=args.format,
                        model=model, voice=args.voice, prompt=args.prompt)

    if not out.exists():
        raise SystemExit(f"レンダラが出力を作らなかった: {out}")

    manifest = _store_put(out)
    stored_sha = manifest["sha256"]
    size = manifest["bytes"]

    # 媒体を作品 JSON と同じフォルダへ置き、相対 path を記録する。
    # verify は作品 JSON からの相対パスで実体と sha256 を照合する。
    work_dir = work_path.resolve().parent
    if out.resolve().parent != work_dir:
        dest = work_dir / out.name
        shutil.copyfile(out, dest)
        out = dest
    rel_path = os.path.relpath(out.resolve(), work_dir)

    core.add_rendition(
        data, str(out), kind=args.kind, format=args.format,
        model=model, model_version=args.model_version, provider=provider,
        prompt=args.prompt, seed=args.seed, voice=args.voice,
        note=f"content-addressed: manifest {manifest['manifest_sha256'][:12]}",
    )
    r = data["renditions"][-1]
    r["path"] = rel_path
    r["sha256"] = stored_sha
    r["bytes"] = size
    r["manifest_sha256"] = manifest["manifest_sha256"]
    r["chunk_count"] = manifest["chunk_count"]
    r["new_bytes"] = manifest["new_bytes"]
    if args.migrate_from:
        r["source_rendition"] = args.migrate_from
        core.append_revision(data, "migrate",
                             note=f"{args.kind} を {model} で再生成")

    print(json.dumps({
        "work": data["id"],
        "rendition_sha256": stored_sha,
        "bytes": size,
        "new_bytes": manifest["new_bytes"],
        "chunks": manifest["chunk_count"],
        "manifest_sha256": manifest["manifest_sha256"],
        "model": model,
        "content_hash": core.content_hash(data),
        "migrated_from": args.migrate_from,
    }, ensure_ascii=False, indent=2))

    if args.write:
        core.dump(data, str(work_path))
        print(f"書き込み: {work_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
