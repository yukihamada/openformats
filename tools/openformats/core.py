"""openformats core library.

1 作品 = 1 JSON。このモジュールが次を担う:

- content_hash: JCS 正規化した本体の SHA-256 (同じ作品 → 同じハッシュ)
- signatures:    content_hash への Ed25519 補助署名
- hash_chain:    前リビジョンへの SHA-256 チェーン (改ざん検知・履歴連続性)
- renditions:    媒体化した実体 (音声/動画/画像) のハッシュと、生成した
                 モデル・プロンプトの来歴。良いモデルが出たら新 rendition を
                 足し、作品本体 (content_hash) は変えない = 「作品は同じ、
                 声だけ差し替え」。

設計原則: 標準ライブラリ + 同梱 ed25519 のみ。外部依存ゼロ。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any

from . import ed25519
from .canonical import canonicalize_bytes

# content_hash の対象から外すフィールド。
# - content_hash: ハッシュ自身
# - signatures:   ハッシュへの署名 (ハッシュに含めると循環する)
# - hash_chain:   履歴チェーン (チェーンは別途 content_hash を鎖状に参照する)
# - renditions:   媒体化の実体。作品の同一性ではなく「出力」なので除外する。
# - provenance.history: 運用ログ (append-only)。作品の創作内容ではなく操作記録。
#                 これらを除外することで「同じ作品のまま、良いモデルで声だけ
#                 差し替える / 改訂を記録する」とき content_hash が不変になる。
#                 履歴の完全性は hash_chain と git 履歴が担保する。
EXCLUDE_FROM_HASH = {"content_hash", "signatures", "hash_chain", "renditions"}


def _body(data: dict) -> dict:
    body = {k: v for k, v in data.items() if k not in EXCLUDE_FROM_HASH}
    # provenance.history は運用ログなので創作内容のハッシュから外す。
    prov = body.get("provenance")
    if isinstance(prov, dict) and "history" in prov:
        prov = {k: v for k, v in prov.items() if k != "history"}
        body["provenance"] = prov
    return body


def content_hash(data: dict) -> str:
    """作品本体 (renditions/署名/チェーンを除く) の JCS-SHA256。"""
    return hashlib.sha256(canonicalize_bytes(_body(data))).hexdigest()


def rendition_hash(path: str) -> str:
    """媒体ファイルの SHA-256 (ストリーミング)。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def unb64(s: str) -> bytes:
    return base64.b64decode(s)


# ---------------------------------------------------------------------------
# keys
# ---------------------------------------------------------------------------

def new_secret() -> bytes:
    return os.urandom(32)


def secret_to_b64(secret: bytes) -> str:
    return b64(secret)


def public_from_secret_b64(secret_b64: str) -> str:
    return b64(ed25519.publickey(unb64(secret_b64)))


# ---------------------------------------------------------------------------
# signing
# ---------------------------------------------------------------------------

def sign_document(data: dict, secret_b64: str, signer: str | None = None,
                  signed_at: str | None = None) -> dict:
    """content_hash を計算し、Ed25519 署名を data['signatures'] に追記する。

    既存の content_hash は再計算して上書きする (常に現本体に一致させる)。
    """
    h = content_hash(data)
    data["content_hash"] = h
    secret = unb64(secret_b64)
    pub = ed25519.publickey(secret)
    sig = ed25519.sign(secret, bytes.fromhex(h))
    entry = {
        "alg": "Ed25519",
        "public_key": b64(pub),
        "signature": b64(sig),
    }
    if signer:
        entry["signer"] = signer
    if signed_at:
        entry["signed_at"] = signed_at
    sigs = [s for s in data.get("signatures", [])
            if not (s.get("public_key") == entry["public_key"])]
    sigs.append(entry)
    data["signatures"] = sigs
    return data


def verify_signatures(data: dict) -> list[dict]:
    """全署名を検証し、結果のリストを返す。"""
    h = content_hash(data)
    results = []
    for s in data.get("signatures", []):
        ok = False
        try:
            ok = ed25519.verify(unb64(s["public_key"]), bytes.fromhex(h),
                                unb64(s["signature"]))
        except Exception:
            ok = False
        results.append({"signer": s.get("signer"), "public_key": s["public_key"],
                        "valid": ok})
    return results


# ---------------------------------------------------------------------------
# versioning (hash_chain)
# ---------------------------------------------------------------------------

def append_revision(data: dict, action: str, by: str | None = None,
                    note: str | None = None, at: str | None = None) -> dict:
    """現在の content_hash を hash_chain の末尾に確定し、履歴を 1 行足す。

    hash_chain は「その作品がこれまでに持った content_hash の順序付き全履歴」
    (現在の頭も含む)。append-only で過去は消さない。内容を編集した後に呼ぶと、
    新しい頭が鎖に積まれる。改ざん・巻き戻しは末尾と現ハッシュの不一致で検知。
    """
    cur = content_hash(data)
    data["content_hash"] = cur
    chain = list(data.get("hash_chain", []))
    if not chain or chain[-1].get("sha256") != cur:
        entry = {"sha256": cur}
        if at:
            entry["at"] = at
        chain.append(entry)
    data["hash_chain"] = chain

    hist = list(data.get("provenance", {}).get("history", []))
    h = {"at": at or _now(), "action": action}
    if by:
        h["by"] = by
    if note:
        h["note"] = note
    hist.append(h)
    data.setdefault("provenance", {})["history"] = hist
    return data


def verify_chain(data: dict) -> dict:
    """hash_chain を検証する。

    hash_chain は現在の頭まで含む全 head 履歴。次を確認する:

    - チェーンが空でないなら、末尾が現在の content_hash と一致 (巻き戻し検知)
    - sha256 に重複がない (履歴の単調性)
    """
    chain = data.get("hash_chain", [])
    cur = content_hash(data)
    problems = []
    if chain and chain[-1].get("sha256") != cur:
        problems.append(
            f"チェーン末尾 {chain[-1].get('sha256')[:12]} が現在の "
            f"content_hash {cur[:12]} と不一致 (内容編集後に revise していない)")
    seen = set()
    for e in chain:
        s = e.get("sha256")
        if s in seen:
            problems.append(f"重複したチェーン要素 {s[:12]}")
        seen.add(s)
    return {"ok": not problems, "length": len(chain), "problems": problems}


# ---------------------------------------------------------------------------
# renditions (media outputs + model provenance)
# ---------------------------------------------------------------------------

def add_rendition(data: dict, path: str, *, kind: str, format: str,
                  model: str | None = None, model_version: str | None = None,
                  prompt: str | None = None, seed: int | None = None,
                  provider: str | None = None, voice: str | None = None,
                  note: str | None = None, at: str | None = None) -> dict:
    """媒体ファイルを作品に紐づける。ファイルの実 SHA-256 を記録する。

    content_hash は変えない (renditions はハッシュ対象外)。これが
    「同じ作品のまま、良いモデルで声だけ差し替える」を可能にする仕組み。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    r = {
        "kind": kind,
        "format": format,
        "sha256": rendition_hash(path),
        "bytes": os.path.getsize(path),
        "generated_at": at or _now(),
    }
    if model:
        r["model"] = model
    if model_version:
        r["model_version"] = model_version
    if provider:
        r["provider"] = provider
    if prompt:
        r["prompt"] = prompt
    if seed is not None:
        r["seed"] = seed
    if voice:
        r["voice"] = voice
    if note:
        r["note"] = note
    data.setdefault("renditions", []).append(r)
    return data


def latest_rendition(data: dict, kind: str | None = None) -> dict | None:
    rs = data.get("renditions", [])
    if kind:
        rs = [r for r in rs if r.get("kind") == kind]
    return rs[-1] if rs else None


# ---------------------------------------------------------------------------
# io
# ---------------------------------------------------------------------------

def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump(data: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
