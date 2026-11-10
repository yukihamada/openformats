"""KOE / teai TTS レンダラ (音声)。

openformats の voice/radio/music 作品を、teai の声ライブラリで音声化する。
実 API 呼び出しは環境変数に依存する。鍵が無い環境では明確に失敗する
(黙って偽の音声を作らない)。

teai の正規経路は非同期:
    POST /api/v1/voice/quote            {"voice": ...} -> {"credits": N, ...}
    POST /api/v1/voice/generate         {voice,text,request_id,confirmed_credits,speed,lang}
    GET  /api/v1/voice/purchases/{id}   state が complete になるまでポーリング
    GET  /api/v1/voice/purchases/{id}/audio -> mp3

環境変数:
    TEAI_API_URL  API ベース (既定: https://teai.io)
    TEAI_API_KEY  認証トークン (例: ~/.config/teai/voice-credentials)
    KOE_VOICE     既定の声 (既定: yukihamada)
    KOE_LANG      読み上げ言語 (既定: ja)
    KOE_SPEED     話速 (既定: 1)

render(data, out, kind, format, model, voice, prompt) を実装する。
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
import uuid

PROVIDER = "teai"
DEFAULT_MODEL = "yukihamada"

POLL_INTERVAL = 3.0
POLL_MAX = 40


def _text_of(data: dict) -> str:
    """作品から読み上げ対象テキストを組み立てる。"""
    parts = []
    for sec in data.get("lyrics", []) or []:
        parts.extend(sec.get("lines", []))
    for seg in data.get("segments", []) or []:
        if seg.get("text"):
            parts.append(seg["text"])
    if data.get("title"):
        parts.insert(0, data["title"])
    return "\n".join(parts).strip()


def _base_url() -> str:
    return (os.environ.get("TEAI_API_URL") or "https://teai.io").rstrip("/")


def _post(path: str, key: str, body: dict) -> dict:
    req = urllib.request.Request(
        _base_url() + path,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(path: str, key: str) -> dict:
    req = urllib.request.Request(
        _base_url() + path,
        headers={"Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_bytes(path: str, key: str) -> bytes:
    req = urllib.request.Request(
        _base_url() + path,
        headers={"Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def render(data, out, *, kind, format, model, voice=None, prompt=None,
           request_id=None):
    key = os.environ.get("TEAI_API_KEY")
    if not key:
        raise RuntimeError(
            "TEAI_API_KEY が未設定。実音声を作るには設定するか、"
            "ドライラン (tools/render.py --dry-run) を使う")

    text = prompt or _text_of(data)
    if not text:
        raise RuntimeError("読み上げ対象テキストが空")

    voice = voice or os.environ.get("KOE_VOICE") or DEFAULT_MODEL
    lang = os.environ.get("KOE_LANG") or "ja"
    speed = float(os.environ.get("KOE_SPEED") or 1)

    quote = _post("/api/v1/voice/quote", key, {"voice": voice})
    credits = quote.get("credits")
    if not isinstance(credits, int):
        raise RuntimeError(f"quote が credits を返さない: {quote}")

    request_id = request_id or str(uuid.uuid4())
    gen = _post("/api/v1/voice/generate", key, {
        "voice": voice,
        "text": text,
        "request_id": request_id,
        "confirmed_credits": credits,
        "speed": speed,
        "lang": lang,
    })
    state = gen.get("state")
    if state == "failed":
        raise RuntimeError(f"generate が失敗: {gen}")

    for _ in range(POLL_MAX):
        if state == "complete":
            break
        time.sleep(POLL_INTERVAL)
        status = _get_json(f"/api/v1/voice/purchases/{request_id}", key)
        state = status.get("state")
        if state == "failed":
            raise RuntimeError(f"生成が失敗: {status}")
    else:
        raise RuntimeError(f"生成がタイムアウト ({POLL_MAX * POLL_INTERVAL:.0f}s)")

    audio = _get_bytes(f"/api/v1/voice/purchases/{request_id}/audio", key)
    if len(audio) < 128:
        raise RuntimeError("TTS 応答が短すぎる (失敗の可能性)")
    with open(out, "wb") as f:
        f.write(audio)

    render.last_request_id = request_id
    render.last_credits = credits
