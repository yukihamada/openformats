"""JSON Patch (RFC 6902) — 差分の生成と適用。外部依存ゼロ。

作品 JSON の「創作内容」(content_hash の対象本体) の版間差分を小さく保存する
ために使う。差分は revisions[] に追記し、content_hash には含めない
(履歴は創作内容ではない)。これにより:

- 保存量は「変えた所だけ」で済む (1万リビジョンでも軽い)。
- 過去のどの版へも checkout で完全復元できる。
- 差分自体も JSON なので、可読・監査可能・git で差分が取れる。

対応 op: add / remove / replace / move / copy / test。
配列インデックスは -  (末尾) を許す。ポインタは RFC 6901。
"""
from __future__ import annotations

import copy
from typing import Any

_MISSING = object()


def _parse_pointer(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"不正な JSON Pointer: {pointer!r}")
    return [t.replace("~1", "/").replace("~0", "~") for t in pointer[1:].split("/")]


def _get(doc: Any, tokens: list[str]) -> Any:
    cur = doc
    for t in tokens:
        if isinstance(cur, list):
            cur = cur[int(t)]
        elif isinstance(cur, dict):
            if t not in cur:
                return _MISSING
            cur = cur[t]
        else:
            return _MISSING
    return cur


def _parent(doc: Any, tokens: list[str]) -> tuple[Any, str]:
    if not tokens:
        raise ValueError("ルートには親が無い")
    return _get(doc, tokens[:-1]), tokens[-1]


def _add(doc: Any, tokens: list[str], value: Any) -> None:
    parent, last = _parent(doc, tokens)
    if isinstance(parent, list):
        idx = len(parent) if last == "-" else int(last)
        parent.insert(idx, value)
    elif isinstance(parent, dict):
        parent[last] = value
    else:
        raise ValueError("add の対象が不正")


def _remove(doc: Any, tokens: list[str]) -> Any:
    parent, last = _parent(doc, tokens)
    if isinstance(parent, list):
        return parent.pop(int(last))
    if isinstance(parent, dict):
        return parent.pop(last)
    raise ValueError("remove の対象が不正")


def apply_patch(doc: Any, patch: list[dict]) -> Any:
    """RFC 6902 パッチを適用した新しい doc を返す (入力は変更しない)。"""
    doc = copy.deepcopy(doc)
    for op in patch:
        path = op.get("path", "")
        tokens = _parse_pointer(path)
        kind = op.get("op")
        if kind == "add":
            if not tokens:
                doc = op["value"]
            else:
                _add(doc, tokens, copy.deepcopy(op["value"]))
        elif kind == "remove":
            _remove(doc, tokens)
        elif kind == "replace":
            if not tokens:
                doc = copy.deepcopy(op["value"])
            else:
                _remove(doc, tokens)
                _add(doc, tokens, copy.deepcopy(op["value"]))
        elif kind == "move":
            val = _remove(doc, _parse_pointer(op["from"]))
            _add(doc, tokens, val)
        elif kind == "copy":
            val = copy.deepcopy(_get(doc, _parse_pointer(op["from"])))
            _add(doc, tokens, val)
        elif kind == "test":
            if _get(doc, tokens) != op.get("value"):
                raise ValueError(f"test 失敗: {path}")
        else:
            raise ValueError(f"未知の op: {kind!r}")
    return doc


def diff(a: Any, b: Any, path: str = "") -> list[dict]:
    """a → b の差分を RFC 6902 パッチとして返す。

    配列はインデックス単位で比較する (音声の配列など順序が意味を持つため)。
    辞書はキー単位。値が等しければ空リスト。
    """
    if a == b:
        return []

    # 型が違う / スカラー → replace
    if not isinstance(a, (dict, list)) or not isinstance(b, (dict, list)) \
            or type(a) is not type(b):
        return [{"op": "replace", "path": path, "value": copy.deepcopy(b)}]

    patch: list[dict] = []

    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k not in b:
                patch.append({"op": "remove", "path": f"{path}/{_esc(k)}"})
        for k in b:
            sub = f"{path}/{_esc(k)}"
            if k not in a:
                patch.append({"op": "add", "path": sub, "value": copy.deepcopy(b[k])})
            else:
                patch.extend(diff(a[k], b[k], sub))
        return patch

    # 配列
    assert isinstance(a, list) and isinstance(b, list)
    common = min(len(a), len(b))
    for i in range(common):
        patch.extend(diff(a[i], b[i], f"{path}/{i}"))
    if len(b) > len(a):
        for i in range(len(a), len(b)):
            patch.append({"op": "add", "path": f"{path}/-", "value": copy.deepcopy(b[i])})
    elif len(a) > len(b):
        # 末尾から削る (インデックスずれを避ける)
        for i in range(len(a) - 1, len(b) - 1, -1):
            patch.append({"op": "remove", "path": f"{path}/{i}"})
    return patch


def _esc(key: str) -> str:
    return str(key).replace("~", "~0").replace("/", "~1")
