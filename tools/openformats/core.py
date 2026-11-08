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
# - revisions:    版間差分 (RFC 6902)。履歴であって創作内容ではない。除外しないと
#                 差分を足すたびに content_hash が変わり「同じ作品」でいられない。
# - provenance.history: 運用ログ (append-only)。作品の創作内容ではなく操作記録。
#                 これらを除外することで「同じ作品のまま、良いモデルで声だけ
#                 差し替える / 改訂を記録する」とき content_hash が不変になる。
#                 履歴の完全性は hash_chain と git 履歴が担保する。
EXCLUDE_FROM_HASH = {"content_hash", "signatures", "hash_chain", "renditions", "revisions"}


def _body(data: dict) -> dict:
    body = {k: v for k, v in data.items() if k not in EXCLUDE_FROM_HASH}
    # provenance.history は運用ログなので創作内容のハッシュから外す。
    prov = body.get("provenance")
    if isinstance(prov, dict) and "history" in prov:
        prov = {k: v for k, v in prov.items() if k != "history"}
        body["provenance"] = prov
    # clone.consent は同意の運用状態 (grant/revoke) であり創作内容ではない。
    # これをハッシュに含めると、撤回のたびに content_hash と既存署名が壊れる。
    # 同意の真正性は clone.consent.events と hash_chain / git 履歴で担保する。
    clone = body.get("clone")
    if isinstance(clone, dict) and "consent" in clone:
        clone = {k: v for k, v in clone.items() if k != "consent"}
        body["clone"] = clone
    # speaker.consent / consent_doc は同意の運用状態 (grant が同期する) であり
    # 創作内容ではない。話者名など他の属性はハッシュ対象のまま。
    speaker = body.get("speaker")
    if isinstance(speaker, dict):
        speaker = {k: v for k, v in speaker.items()
                   if k not in ("consent", "consent_doc")}
        if speaker:
            body["speaker"] = speaker
        else:
            body.pop("speaker", None)
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
# revisions (版間差分の記録 = エンコーダ/レコーダ)
# ---------------------------------------------------------------------------
#
# 作品の「創作内容」(content_hash の対象本体) の版間差分を RFC 6902 で保存する。
# 差分は revisions[] に追記し、content_hash には含めない (履歴は創作内容でない)。
# これで「変えた所だけ」を保存しつつ、任意の版へ完全復元できる。

def _snapshot(data: dict) -> dict:
    """content_hash の対象本体 (履歴・媒体・署名を除く) を深いコピーで取り出す。

    深いコピー必須: 浅いコピーだと snapshot が本体の入れ子を共有し、後で本体を
    編集すると過去のスナップショットまで書き換わって差分が消える。
    """
    import copy
    return copy.deepcopy(_body(data))


def _reconstruct(revs: list[dict], upto: int) -> dict:
    """revs[0] の base スナップショットから patch を順に適用し upto 時点を復元。

    戻り値は必ず deepcopy。base snapshot を共有したまま返すと、呼び出し側が
    復元結果を編集したときに履歴 (revisions[0].snapshot) まで書き換わる。
    """
    import copy
    from . import jsonpatch

    body = copy.deepcopy(revs[0]["snapshot"])
    for i in range(1, upto + 1):
        body = jsonpatch.apply_patch(body, revs[i].get("patch", []))
    return body


def record_revision(data: dict, *, action: str = "edit", by: str | None = None,
                    note: str | None = None, at: str | None = None) -> dict:
    """現在の本体と直前版の差分を revisions に追記する (差分保存)。

    - 初回: base スナップショット (本体全体) を 1 つだけ保存する。
    - 2 回目以降: 直前版との差分 (RFC 6902 patch) だけを保存する。

    直前版は base + 既存 patch から復元するので、全スナップショットを積まない。
    これが「1万リビジョンでも軽い」理由。
    """
    from . import jsonpatch

    cur = _snapshot(data)
    revs = list(data.get("revisions", []))
    if not revs:
        entry = {
            "at": at or _now(),
            "action": action,
            "content_hash": content_hash(data),
            "patch": [],
            "snapshot": cur,
        }
        if by:
            entry["by"] = by
        if note:
            entry["note"] = note
        revs.append(entry)
        data["revisions"] = revs
        return data

    prev = _reconstruct(revs, len(revs) - 1)
    patch = jsonpatch.diff(prev, cur)
    entry = {
        "at": at or _now(),
        "action": action,
        "content_hash": content_hash(data),
        "patch": patch,
    }
    if by:
        entry["by"] = by
    if note:
        entry["note"] = note
    revs.append(entry)
    data["revisions"] = revs
    return data


def checkout(data: dict, index: int) -> dict:
    """revisions[index] 時点の本体を復元した新しい作品 dict を返す。

    index は revisions の 0 始まり。復元は base スナップショットから patch を
    順に適用して行う。返すのは「創作内容」のみ (renditions/revisions/署名は
    含めない)。媒体や署名は別途付け直す。
    """
    revs = data.get("revisions", [])
    if not revs:
        raise ValueError("revisions が無い")
    if not (0 <= index < len(revs)):
        raise IndexError(f"index 範囲外: {index} (0..{len(revs) - 1})")
    return _reconstruct(revs, index)


def verify_revisions(data: dict) -> dict:
    """revisions と現在の本体が整合しているかを検査する。

    最後の revision を復元した内容が現在の本体 (_body) と一致し、かつ記録された
    content_hash が現在の content_hash と一致することを確認する。履歴が本体と
    食い違ったまま (編集後に record していない等) なら problems に残す。
    """
    revs = data.get("revisions", [])
    if not revs:
        return {"ok": True, "length": 0, "problems": []}
    problems = []
    try:
        restored = _reconstruct(revs, len(revs) - 1)
    except Exception as e:
        return {"ok": False, "length": len(revs),
                "problems": [f"最終リビジョンを復元できない: {e}"]}
    body = _body(data)
    if restored != body:
        problems.append("最終リビジョンの復元内容が現在の本体と不一致 (record 漏れの可能性)")
    recorded = revs[-1].get("content_hash")
    cur = content_hash(data)
    if recorded and recorded != cur:
        problems.append(
            f"最終リビジョンの記録ハッシュ {recorded[:12]} が現在の content_hash "
            f"{cur[:12]} と不一致")
    return {"ok": not problems, "length": len(revs), "problems": problems}


def revision_log(data: dict) -> list[dict]:
    """revisions の要約 (index/at/action/by/note/hash/patch_size)。"""
    log = []
    for i, r in enumerate(data.get("revisions", [])):
        log.append({
            "index": i,
            "at": r.get("at"),
            "action": r.get("action"),
            "by": r.get("by"),
            "note": r.get("note"),
            "content_hash": r.get("content_hash"),
            "patch_ops": len(r.get("patch", [])),
        })
    return log


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
