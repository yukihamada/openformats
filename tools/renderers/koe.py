"""KOE / teai TTS レンダラ (音声)。

openformats の voice/radio/music 作品を、KOE の TTS で音声化する。
実 API 呼び出しは環境変数に依存する。鍵が無い環境では明確に失敗する
(黙って偽の音声を作らない)。

環境変数:
    KOE_API_URL   TTS エンドポイント (例: https://koe.live/api/tts)
    KOE_API_KEY   認証トークン
    KOE_VOICE     既定の声 id (作品の rendition.voice で上書き可)

render(data, out, kind, format, model, voice, prompt) を実装する。
"""
from __future__ import annotations

import json
import os
import urllib.request

PROVIDER = "koe"
DEFAULT_MODEL = "koe-tts"


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


def render(data, out, *, kind, format, model, voice=None, prompt=None):
    url = os.environ.get("KOE_API_URL")
    key = os.environ.get("KOE_API_KEY")
    if not url or not key:
        raise RuntimeError(
            "KOE_API_URL / KOE_API_KEY が未設定。実音声を作るには設定するか、"
            "ドライラン (tools/render.py --dry-run) を使う")

    text = prompt or _text_of(data)
    if not text:
        raise RuntimeError("読み上げ対象テキストが空")

    body = json.dumps({
        "text": text,
        "voice": voice or os.environ.get("KOE_VOICE"),
        "model": model,
        "format": format,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        audio = resp.read()
    if len(audio) < 128:
        raise RuntimeError("TTS 応答が短すぎる (失敗の可能性)")
    with open(out, "wb") as f:
        f.write(audio)
