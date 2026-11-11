"""radio 作品の意味検証。JSON Schema では表しにくい参照・タイムラインの整合を検査する。

外部依存なし。validate.py とテストの両方から使う。
"""


def semantic_errors(data):
    """作品データの意味的な不整合を (loc, message) のリストで返す。

    現在は radio のみ対象:
      - speakers[].id の一意性
      - speech.speaker が speakers[].id を参照していること
      - start_sec が直前の終端より前でないこと（タイムラインの単調性）
    """
    out = []
    if not isinstance(data, dict) or data.get("kind") != "radio":
        return out

    speakers = data.get("speakers") or []
    ids = [s.get("id") for s in speakers if isinstance(s, dict)]
    seen = set()
    for sid in ids:
        if sid in seen:
            out.append(("speakers", f"話者 id が重複しています: {sid!r}"))
        seen.add(sid)
    known = {i for i in ids if i}

    prev_end = 0.0
    for i, seg in enumerate(data.get("segments") or []):
        if not isinstance(seg, dict):
            continue
        loc = f"segments/{i}"
        if seg.get("type") == "speech":
            spk = seg.get("speaker")
            if spk is not None and spk not in known:
                out.append((loc, f"speaker {spk!r} が speakers[].id に存在しません"))
        start = seg.get("start_sec")
        dur = seg.get("duration_sec") or 0
        if start is not None:
            if start < prev_end - 0.05:
                out.append((loc, f"start_sec {start} が直前の終端 {prev_end:.3f} より前です"))
            prev_end = max(prev_end, start + dur)
    return out
