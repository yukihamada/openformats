"""Pure-Python Ed25519 (RFC 8032).

外部依存ゼロで署名・検証する。content_hash に対する補助署名に使う。
性能より可搬性と監査容易性を優先する (作品ごとに 1 回署名するだけ)。

This is the reference implementation logic from RFC 8032 / the public-domain
ed25519.py by DJB / Python "pure" variant. Kept small and readable on purpose.
"""
from __future__ import annotations

import hashlib

p = 2**255 - 19
q = 2**252 + 27742317777372353535851937790883648493


def _inv(x):
    return pow(x, p - 2, p)


d = -121665 * _inv(121666) % p
I = pow(2, (p - 1) // 4, p)


def _xrecover(y):
    xx = (y * y - 1) * _inv(d * y * y + 1)
    x = pow(xx, (p + 3) // 8, p)
    if (x * x - xx) % p != 0:
        x = (x * I) % p
    if x % 2 != 0:
        x = p - x
    return x


By = 4 * _inv(5) % p
Bx = _xrecover(By)
B = (Bx % p, By % p)


def _edwards_add(P, Q):
    x1, y1 = P
    x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + d * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - d * x1 * x2 * y1 * y2)
    return (x3 % p, y3 % p)


def _scalarmult(P, e):
    if e == 0:
        return (0, 1)
    Q = _scalarmult(P, e // 2)
    Q = _edwards_add(Q, Q)
    if e & 1:
        Q = _edwards_add(Q, P)
    return Q


def _encodeint(y):
    return y.to_bytes(32, "little")


def _encodepoint(P):
    x, y = P
    bits = y | ((x & 1) << 255)
    return bits.to_bytes(32, "little")


def _bit(h, i):
    return (h[i // 8] >> (i % 8)) & 1


def _H(m):
    return hashlib.sha512(m).digest()


def _secret_expand(secret: bytes):
    h = _H(secret)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def publickey(secret: bytes) -> bytes:
    a, _ = _secret_expand(secret)
    return _encodepoint(_scalarmult(B, a))


def _Hint(m):
    h = _H(m)
    return int.from_bytes(h, "little")


def sign(secret: bytes, msg: bytes) -> bytes:
    a, prefix = _secret_expand(secret)
    A = _encodepoint(_scalarmult(B, a))
    r = _Hint(prefix + msg)
    R = _scalarmult(B, r)
    S = (r + _Hint(_encodepoint(R) + A + msg) * a) % q
    return _encodepoint(R) + _encodeint(S)


def _isoncurve(P):
    x, y = P
    return (-x * x + y * y - 1 - d * x * x * y * y) % p == 0


def _decodeint(s):
    return int.from_bytes(s, "little")


def _decodepoint(s: bytes):
    y = int.from_bytes(s, "little") & ((1 << 255) - 1)
    x = _xrecover(y)
    if x & 1 != _bit(s, 255):
        x = p - x
    P = (x, y)
    if not _isoncurve(P):
        raise ValueError("点が曲線上にない")
    return P


def verify(public: bytes, msg: bytes, signature: bytes) -> bool:
    if len(signature) != 64 or len(public) != 32:
        return False
    try:
        R = _decodepoint(signature[:32])
        A = _decodepoint(public)
    except ValueError:
        return False
    S = _decodeint(signature[32:])
    if S >= q:
        return False
    h = _Hint(signature[:32] + public + msg)
    return _scalarmult(B, S) == _edwards_add(R, _scalarmult(A, h))
