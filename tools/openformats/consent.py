"""声クローンの同意フロー — 作成・配布・撤回を状態機械で管理する。外部依存ゼロ。

声の再現は、話者の同意が前提。この同意を「口約束」でなく構造として残す。
状態遷移:
    requested → granted → (revoked)
    requested → denied
    granted   → revoked   (話者がいつでも撤回できる)

各遷移は履歴 (events) に追記され、現在の状態は events から導出する。
撤回 (revoked) されたら、そのクローンを使った合成・配布を禁止する。

voice.json の clone ブロックに consent オブジェクトを埋め込む:
    clone.consent = {
      "status": "granted",
      "subject": "濱田優貴",           # 同意した話者
      "granted_by": "self",            # 同意の主体 (self / guardian / licensee)
      "scope": ["tts", "render"],      # 許諾する用途
      "doc": "internal:voice-consent-2026",
      "events": [ {at, action, by, note}, ... ]
    }

使い方 (ライブラリ):
    from openformats import consent
    consent.request(data, subject="濱田優貴", doc="...")
    consent.grant(data, by="self", scope=["tts"])
    consent.revoke(data, by="self", note="配布停止")
    consent.status(data)      # -> "granted" / "revoked" / ...
    consent.can_synthesize(data)  # -> bool (granted かつ撤回されていない)

使い方 (CLI):
    python3 tools/of.py consent status work.voice.json
    python3 tools/of.py consent request work.voice.json --subject 濱田優貴 --doc ...
    python3 tools/of.py consent grant work.voice.json --by self --scope tts --scope render --write
    python3 tools/of.py consent revoke work.voice.json --by self --note "配布停止" --write
"""
from __future__ import annotations

import datetime as _dt

VALID_ACTIONS = {"request", "grant", "deny", "revoke"}
TERMINAL = {"revoked", "denied"}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _consent(data: dict) -> dict:
    clone = data.setdefault("clone", {})
    c = clone.setdefault("consent", {})
    c.setdefault("events", [])
    return c


def _append(c: dict, action: str, *, by: str | None, note: str | None, **extra) -> None:
    ev = {"at": _now(), "action": action}
    if by:
        ev["by"] = by
    if note:
        ev["note"] = note
    ev.update(extra)
    c["events"].append(ev)


def request(data: dict, *, subject: str, doc: str | None = None,
            by: str | None = None, note: str | None = None) -> dict:
    c = _consent(data)
    c["subject"] = subject
    if doc:
        c["doc"] = doc
    c["status"] = "requested"
    _append(c, "request", by=by or subject, note=note)
    return data


def grant(data: dict, *, by: str = "self", scope: list[str] | None = None,
          doc: str | None = None, note: str | None = None) -> dict:
    c = _consent(data)
    st = c.get("status")
    if st in TERMINAL:
        raise ValueError(f"{st} 済みの同意は grant できない。再度 request から。")
    c["status"] = "granted"
    c["granted_by"] = by
    if scope:
        c["scope"] = list(scope)
    if doc:
        c["doc"] = doc
    _append(c, "grant", by=by, note=note, scope=scope or c.get("scope"))
    # speaker.consent も同期 (既存の検証と整合)
    sp = data.setdefault("speaker", {})
    if by == "self":
        sp["consent"] = "self"
    elif by in ("licensee", "licensed"):
        sp["consent"] = "licensed"
    if doc:
        sp["consent_doc"] = doc
    return data


def deny(data: dict, *, by: str | None = None, note: str | None = None) -> dict:
    c = _consent(data)
    c["status"] = "denied"
    _append(c, "deny", by=by, note=note)
    return data


def revoke(data: dict, *, by: str = "self", note: str | None = None) -> dict:
    c = _consent(data)
    if c.get("status") not in ("granted", "requested"):
        raise ValueError(f"撤回できない状態: {c.get('status')}")
    c["status"] = "revoked"
    _append(c, "revoke", by=by, note=note)
    return data


def status(data: dict) -> str | None:
    return data.get("clone", {}).get("consent", {}).get("status")


def can_synthesize(data: dict) -> bool:
    """このクローンで合成してよいか。granted かつ撤回されていないこと。"""
    c = data.get("clone", {}).get("consent", {})
    if c.get("status") != "granted":
        return False
    # 最新イベントが revoke なら不可 (履歴の取り違え防止)
    events = c.get("events", [])
    if events and events[-1].get("action") == "revoke":
        return False
    return True


def scope_allows(data: dict, use: str) -> bool:
    """指定用途 (tts / render / distribute) が許諾範囲か。scope 未指定なら tts のみ許可。"""
    c = data.get("clone", {}).get("consent", {})
    scope = c.get("scope") or ["tts"]
    return use in scope


def validate(data: dict) -> list[str]:
    """同意フローの整合性を検査する。"""
    problems: list[str] = []
    clone = data.get("clone")
    if not clone:
        return problems
    c = clone.get("consent", {})
    st = c.get("status")
    if not st:
        # consent ブロックが無い場合は speaker.consent で後方互換チェック
        sp = data.get("speaker", {})
        if sp.get("consent") not in ("self", "licensed", "public-domain"):
            problems.append("clone があるのに同意 (clone.consent / speaker.consent) が無い")
        return problems
    if st not in ("requested", "granted", "denied", "revoked"):
        problems.append(f"未知の同意状態: {st}")
    if st == "granted" and not c.get("granted_by"):
        problems.append("granted なのに granted_by が無い")
    if st == "granted" and not c.get("events"):
        problems.append("granted なのに履歴 (events) が無い")
    if st == "revoked" and c.get("events") and c["events"][-1].get("action") != "revoke":
        problems.append("revoked なのに最後のイベントが revoke でない")
    return problems
