"""RFC 8785 JSON Canonicalization Scheme (JCS).

content_hash は「同じ作品 → 同じハッシュ」でなければならない。
そのため JSON を RFC 8785 に従って正規化してから SHA-256 を取る。

- オブジェクトのキーは UTF-16 コードユニット順にソート
- 数値は ECMAScript Number::toString と同じ最短表現
- 文字列は ECMAScript JSON.stringify と同じエスケープ
- 空白なし、UTF-8 出力

外部依存なし。100 年後も Python 標準ライブラリだけで再現できる。
"""
from __future__ import annotations

import math


class CanonicalizationError(ValueError):
    pass


def _num_to_es(x) -> str:
    """ECMAScript Number::toString に一致する数値表現を返す。"""
    if isinstance(x, bool):
        raise CanonicalizationError("bool は数値として扱わない")
    if isinstance(x, int):
        return str(x)
    if not isinstance(x, float):
        raise CanonicalizationError(f"未対応の数値型: {type(x)!r}")
    if math.isnan(x) or math.isinf(x):
        raise CanonicalizationError("NaN / Infinity は JSON で表現できない")
    if x == 0:
        return "0"  # -0 も "0"

    neg = x < 0
    s = repr(abs(x))

    if "e" in s or "E" in s:
        mant, _, exp_s = s.partition("e") if "e" in s else s.partition("E")
        exp = int(exp_s)
    else:
        mant, exp = s, 0

    if "." in mant:
        int_part, frac_part = mant.split(".")
    else:
        int_part, frac_part = mant, ""

    digits = int_part + frac_part
    point = len(int_part) + exp  # 小数点が digits の先頭から何桁目か

    # 先頭の 0 を落とす
    lead = 0
    while lead < len(digits) and digits[lead] == "0":
        lead += 1
    digits = digits[lead:]
    point -= lead

    if digits == "":
        return "0"

    # 末尾の 0 を落とす (値は変わらない)
    digits = digits.rstrip("0")
    if digits == "":
        return "0"

    k = len(digits)
    n = point

    if k <= n <= 21:
        out = digits + "0" * (n - k)
    elif 0 < n <= 21:
        out = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        out = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        sign = "+" if e >= 0 else "-"
        if k == 1:
            out = digits + "e" + sign + str(abs(e))
        else:
            out = digits[0] + "." + digits[1:] + "e" + sign + str(abs(e))

    return ("-" if neg else "") + out


_ESCAPE = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def _escape_string(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch in _ESCAPE:
            out.append(_ESCAPE[ch])
        elif ch < " ":
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _key_sort_key(k: str):
    # UTF-16 コードユニット順
    return k.encode("utf-16-be")


def canonicalize(value) -> str:
    """値を JCS 文字列に変換する。"""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return _num_to_es(value)
    if isinstance(value, str):
        return _escape_string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonicalize(v) for v in value) + "]"
    if isinstance(value, dict):
        items = []
        for k in sorted(value.keys(), key=_key_sort_key):
            if not isinstance(k, str):
                raise CanonicalizationError("オブジェクトのキーは文字列のみ")
            items.append(_escape_string(k) + ":" + canonicalize(value[k]))
        return "{" + ",".join(items) + "}"
    raise CanonicalizationError(f"未対応の型: {type(value)!r}")


def canonicalize_bytes(value) -> bytes:
    return canonicalize(value).encode("utf-8")
