"""長文を 600 字以内のチャンクに分けて teai で合成し、1 本に結合する。

teai の voice/generate は 1 リクエスト 600 字上限 (verbatim)。movie や
podcast のような長い台本は、文の境界で区切って複数回合成し、ffmpeg で
つなぐ。句点・読点・改行を優先し、無理に単語の途中で切らない。

使い方:
    python3 tools/render_long.py <work.json> --kind audio --format mp3 \
        --renderer koe --out out.mp3 --write

環境変数は tools/renderers/koe.py と同じ (TEAI_API_KEY 等)。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "renderers"))

from openformats import core  # noqa: E402
import koe  # noqa: E402

MAX_CHARS = 600


def _segments_text(data: dict) -> list[str]:
    """作品から読み上げ単位 (段落) のリストを作る。"""
    out: list[str] = []
    for seg in data.get("segments", []) or []:
        if seg.get("type") == "speech" and seg.get("text"):
            out.append(seg["text"].strip())
    for sec in data.get("lyrics", []) or []:
        lines = [l for l in sec.get("lines", []) if l and not l.startswith("（")]
        if lines:
            out.append("\n".join(lines))
    for sc in data.get("scenes", []) or []:
        lines = sc.get("lines", [])
        if lines:
            out.append("\n".join(lines))
    return [p for p in out if p]


def _split(text: str, limit: int = MAX_CHARS) -> list[str]:
    """文境界で limit 以内に区切る。1 文が limit 超なら読点で割る。"""
    if len(text) <= limit:
        return [text]
    # まず文単位に分解
    import re
    sentences = re.split(r"(?<=[。！？!?\n])", text)
    chunks: list[str] = []
    buf = ""
    for s in sentences:
        if not s:
            continue
        if len(s) > limit:
            # 長すぎる 1 文は読点で割る
            parts = re.split(r"(?<=[、,])", s)
            for p in parts:
                if len(buf) + len(p) > limit and buf:
                    chunks.append(buf)
                    buf = ""
                if len(p) > limit:
                    # それでも長い: 強制分割
                    for i in range(0, len(p), limit):
                        chunks.append(p[i:i + limit])
                else:
                    buf += p
            continue
        if len(buf) + len(s) > limit and buf:
            chunks.append(buf)
            buf = ""
        buf += s
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c.strip()]


def _render_with_retry(text: str, part: str, voice: str, rid: str,
                       tries: int = 4) -> None:
    """1 チャンクを合成する。通信切断は同じ request_id で再試行する。

    request_id は決定的なので、既に課金済みの文は再課金されずに結果が返る。
    生成済みの part ファイルがあればスキップして再開できる。
    """
    if os.path.exists(part) and os.path.getsize(part) > 128:
        print(f"  既存を再利用: {os.path.basename(part)}", file=sys.stderr)
        return
    last = None
    for attempt in range(1, tries + 1):
        try:
            koe.render({"segments": [{"text": text}]}, part,
                       kind="audio", format="mp3", model=voice,
                       voice=voice, request_id=rid)
            return
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  試行 {attempt}/{tries} 失敗: {e}", file=sys.stderr)
            if attempt < tries:
                time.sleep(3 * attempt)
    raise RuntimeError(f"合成に失敗 ({tries}回): {last}")


def _concat_mp3(parts: list[str], out: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")
        listfile = f.name
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
             "-c", "copy", out],
            check=True, capture_output=True,
        )
    finally:
        os.unlink(listfile)


def main(argv):
    ap = argparse.ArgumentParser(description="長文を分割して音声化し結合する")
    ap.add_argument("work")
    ap.add_argument("--kind", default="audio")
    ap.add_argument("--format", default="mp3")
    ap.add_argument("--renderer", default="koe")
    ap.add_argument("--voice", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv[1:])

    data = core.load(args.work)
    paras = _segments_text(data)
    if not paras:
        raise SystemExit("読み上げ対象の段落が空")

    chunks: list[str] = []
    for p in paras:
        chunks.extend(_split(p))

    key = os.environ.get("TEAI_API_KEY")
    if not key:
        raise SystemExit("TEAI_API_KEY 未設定")

    voice = args.voice or os.environ.get("KOE_VOICE") or koe.DEFAULT_MODEL
    # 作品ごとに固定の作業ディレクトリ。中断しても生成済み part を再利用する。
    tmpdir = os.path.join(tempfile.gettempdir(), f"of-long-{data['id']}")
    os.makedirs(tmpdir, exist_ok=True)
    parts: list[str] = []
    total_credits = 0
    for i, ch in enumerate(chunks):
        part = os.path.join(tmpdir, f"part-{i:03d}.mp3")
        print(f"[{i+1}/{len(chunks)}] {len(ch)}字 合成中…", file=sys.stderr)
        # テキストから決定的な request_id を作る。同じ文は再課金されない
        # (teai の冪等キー) ので、通信切断後の再実行で二重課金しない。
        rid = str(uuid.uuid5(uuid.NAMESPACE_URL,
                             f"openformats:{voice}:{ch}"))
        _render_with_retry(ch, part, voice, rid)
        total_credits += getattr(koe.render, "last_credits", 0)
        parts.append(part)

    _concat_mp3(parts, args.out)
    size = os.path.getsize(args.out)

    # 作品フォルダへ置き、rendition を記録
    work_dir = pathlib.Path(args.work).resolve().parent
    dest = work_dir / os.path.basename(args.out)
    if os.path.abspath(args.out) != str(dest):
        import shutil
        shutil.copyfile(args.out, dest)
    rel = os.path.relpath(dest, work_dir)
    core.add_rendition(data, str(dest), kind=args.kind, format=args.format,
                       model=voice, provider="teai", voice=voice,
                       note=f"long-form: {len(chunks)} chunks, {total_credits}cr")
    r = data["renditions"][-1]
    r["path"] = rel
    r["bytes"] = size
    r["chunk_count"] = len(chunks)
    if args.write:
        core.dump(data, args.work)

    print(json.dumps({
        "work": data["id"], "chunks": len(chunks),
        "bytes": size, "credits": total_credits, "path": rel,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
