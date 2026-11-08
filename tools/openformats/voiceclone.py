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
                     max_inline_bytes: int = 2_000_000) -> dict:
    """参照音声を clone.reference に取り込む。

    小さい音声 (既定 2MB 以下) は base64 で JSON に内包して自己完結させる。
    大きい音声は blob 参照 (sha256) のみ記録し、実体はストアに置く。
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

    clone = data.get("clone", {})
    clone.setdefault("engine", engine)
    clone.setdefault("method", "zero-shot")
    clone["reference"] = ref
    data["clone"] = clone
    return data


def reference_bytes(data: dict) -> bytes | None:
    """clone.reference の参照音声バイト列を返す (内包 or ストアから復元)。"""
    ref = data.get("clone", {}).get("reference", {})
    if ref.get("audio_b64"):
        return base64.b64decode(ref["audio_b64"])
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


def qwen_tts_args(data: dict) -> dict:
    """qwen-tts (Qwen3-TTS / Qwen2.5-Omni 系) に渡すクローン引数を組み立てる。

    返す dict は一般的な zero-shot クローン API の kwargs 形:
        {"ref_audio": <bytes か path>, "ref_text": str, "x_vector_only": bool,
         "language": str, "params": {...}}

    実エンジンの引数名はラッパーで吸収する想定。ここでは意味を保った中立形。
    """
    clone = data.get("clone", {})
    ref = clone.get("reference", {})
    emb = clone.get("embedding", {})
    out: dict = {
        "engine": clone.get("engine", "qwen-tts"),
        "method": clone.get("method", "zero-shot"),
        "language": ref.get("lang") or data.get("lang"),
        "params": clone.get("params", {}),
    }
    rb = reference_bytes(data)
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
    """クローンを作ってよい同意があるか。"""
    sp = data.get("speaker", {})
    consent = sp.get("consent")
    env = data.get("consent", {})
    status = env.get("status")
    if consent in ("self", "licensed", "public-domain"):
        return True
    if status == "granted":
        return True
    return False


def validate_clone(data: dict) -> list[str]:
    """clone ブロックの自己完結性・同意を検査し、問題のリストを返す。"""
    problems: list[str] = []
    clone = data.get("clone")
    if not clone:
        return problems
    if not consent_ok(data):
        problems.append("clone があるのに声の同意 (speaker.consent / consent.status) が無い")
    ref = clone.get("reference", {})
    emb = clone.get("embedding", {})
    if clone.get("method") in ("zero-shot", "hybrid"):
        if not (ref.get("audio_b64") or ref.get("audio_sha256") or ref.get("audio_manifest")):
            problems.append("zero-shot なのに参照音声 (audio_b64/sha256/manifest) が無い")
        if not ref.get("text") and not clone.get("params", {}).get("x_vector_only"):
            problems.append("zero-shot なのに参照テキスト (ref_text) が無い")
    if clone.get("method") in ("embedding", "hybrid"):
        if not emb.get("audio_b64"):
            problems.append("embedding 方式なのに話者埋め込みが無い")
    return problems
