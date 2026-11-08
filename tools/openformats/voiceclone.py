"""声の再現 (voice clone) — qwen-tts 等の zero-shot クローン入力を組み立てる。

voice.json の clone ブロックを読み書きし、参照音声・参照テキスト・話者埋め込みを
テキスト(base64)で自己完結させる。フォークした人がこの JSON だけで同じ声を
再現できることを目的とする。外部依存ゼロ。

使い方 (ライブラリ):
    from openformats import voiceclone
    voiceclone.attach_reference(data, "ref.wav", text="こんにちは", lang="ja")
    args = voiceclone.qwen_tts_args(data)  # qwen-tts に渡す kwargs

CLI は tools/of.py の voice-* サブコマンドから呼ぶ。
"""
from __future__ import annotations

import base64
import hashlib
import pathlib


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def attach_reference(data: dict, audio_path: str, *, text: str, lang: str | None = None,
                     engine: str = "qwen-tts", embed: bool = True,
                     max_inline_bytes: int = 2_000_000, store=None) -> dict:
    """参照音声を clone.reference に取り込む。

    小さい音声 (既定 2MB 以下) は base64 で JSON に内包して自己完結させる。
    大きい音声は実体を content-addressed ストアに保存し、参照 (sha256) を記録する。
    ストアが渡されないのに内包サイズを超える場合は、実体を失わないよう
    ValueError を投げる (黙ってバイト列を捨てない)。
    """
    p = pathlib.Path(audio_path)
    raw = p.read_bytes()
    sha = _sha256(raw)
    fmt = p.suffix.lstrip(".").lower() or "wav"

    ref = {
        "text": text,
        "audio_format": fmt,
        "audio_sha256": sha,
    }
    if lang:
        ref["lang"] = lang
    if embed and len(raw) <= max_inline_bytes:
        ref["audio_b64"] = _b64(raw)
    elif store is not None:
        s, _ = store.put_bytes(raw)
        ref["audio_sha256"] = s
        ref["audio_store"] = "ofstore"
    else:
        raise ValueError(
            f"参照音声が {max_inline_bytes} バイトを超える。実体を保持するには "
            f"store を渡すか max_inline_bytes を増やすこと (黙って捨てない)")

    clone = data.get("clone", {})
    clone.setdefault("engine", engine)
    clone.setdefault("method", "zero-shot")
    clone["reference"] = ref
    data["clone"] = clone
    return data


def reference_bytes(data: dict, store=None) -> bytes | None:
    """clone.reference の参照音声バイト列を返す (内包 or ストアから復元)。"""
    ref = data.get("clone", {}).get("reference", {})
    if ref.get("audio_b64"):
        return base64.b64decode(ref["audio_b64"])
    if ref.get("audio_sha256") and store is not None:
        try:
            return store.get_bytes(ref["audio_sha256"])
        except FileNotFoundError:
            return None
    return None


def attach_embedding(data: dict, vector_b64: str, *, dim: int,
                     dtype: str = "float32", engine: str = "qwen-tts") -> dict:
    """話者埋め込み (embedding) を clone.embedding に取り込む。"""
    clone = data.get("clone", {})
    clone.setdefault("engine", engine)
    clone["method"] = "embedding"
    clone["embedding"] = {
        "audio_b64": vector_b64,
        "dim": dim,
        "dtype": dtype,
        "sha256": _sha256(base64.b64decode(vector_b64)),
    }
    data["clone"] = clone
    return data


def qwen_tts_args(data: dict, store=None) -> dict:
    """qwen-tts (Qwen3-TTS / Qwen2.5-Omni 系) に渡すクローン引数を組み立てる。

    返す dict は一般的な zero-shot クローン API の kwargs 形:
        {"ref_audio": <bytes か path>, "ref_text": str, "x_vector_only": bool,
         "language": str, "params": {...}}

    実エンジンの引数名はラッパーで吸収する想定。ここでは意味を保った中立形。

    合成は同意が有効な場合のみ許可する。撤回・拒否済みなら ValueError を投げる
    (呼び出し側の検査漏れでも合成引数を生成しないための最終防衛線)。
    """
    if not consent_ok(data):
        raise PermissionError("声の同意が無効 (撤回/拒否/未同意) のため合成引数を生成できない")
    from . import consent as _consent
    if not _consent.scope_allows(data, "tts"):
        raise PermissionError("同意 scope に tts が含まれないため合成できない")
    clone = data.get("clone", {})
    ref = clone.get("reference", {})
    emb = clone.get("embedding", {})
    out: dict = {
        "engine": clone.get("engine", "qwen-tts"),
        "method": clone.get("method", "zero-shot"),
        "language": ref.get("lang") or data.get("lang"),
        "params": clone.get("params", {}),
    }
    rb = reference_bytes(data, store=store)
    if rb is not None:
        out["ref_audio"] = rb
    elif ref.get("audio_sha256"):
        out["ref_audio_sha256"] = ref["audio_sha256"]
    if ref.get("text"):
        out["ref_text"] = ref["text"]
    if emb.get("audio_b64"):
        out["speaker_embedding_b64"] = emb["audio_b64"]
        out["embedding_dim"] = emb.get("dim")
    if clone.get("params", {}).get("x_vector_only"):
        out["x_vector_only"] = True
    return out


def consent_ok(data: dict) -> bool:
    """クローンを作ってよい同意があるか。

    clone.consent がある場合は同意状態機械 (consent モジュール) を唯一の真実とし、
    撤回 (revoked)・拒否 (denied) を必ず拒否する。clone.consent が無い場合のみ
    speaker.consent による後方互換チェックを行う。
    """
    from . import consent as _consent

    c = data.get("clone", {}).get("consent", {})
    if c.get("status"):
        return _consent.can_synthesize(data)
    # 後方互換: 同意ブロックが無い旧データ
    sp = data.get("speaker", {})
    return sp.get("consent") in ("self", "licensed", "public-domain")


def validate_clone(data: dict, store=None) -> list[str]:
    """clone ブロックの自己完結性・同意を検査し、問題のリストを返す。"""
    problems: list[str] = []
    clone = data.get("clone")
    if not clone:
        return problems
    if not consent_ok(data):
        from . import consent as _consent
        st = _consent.status(data)
        if st in ("revoked", "denied"):
            problems.append(f"声の同意が {st} のため合成できない")
        else:
            problems.append("clone があるのに声の同意 (speaker.consent / clone.consent) が無い")
    ref = clone.get("reference", {})
    emb = clone.get("embedding", {})
    if clone.get("method") in ("zero-shot", "hybrid"):
        has_ref = bool(ref.get("audio_b64") or ref.get("audio_sha256")
                       or ref.get("audio_manifest"))
        if not has_ref:
            problems.append("zero-shot なのに参照音声 (audio_b64/sha256/manifest) が無い")
        elif not ref.get("audio_b64") and store is not None \
                and reference_bytes(data, store=store) is None:
            problems.append("参照音声がストアに無く復元できない (audio_sha256 のみ)")
        if not ref.get("text") and not clone.get("params", {}).get("x_vector_only"):
            problems.append("zero-shot なのに参照テキスト (ref_text) が無い")
    if clone.get("method") in ("embedding", "hybrid"):
        if not emb.get("audio_b64"):
            problems.append("embedding 方式なのに話者埋め込みが無い")
    return problems
