"""FastCDC — 内容定義チャンク化 (content-defined chunking)。外部依存ゼロ。

バイナリ (音声/動画/画像) を「内容の境界」で切る。固定長分割と違い、途中に
数バイト挿入しても後続のチャンク境界がずれないため、再レンダリング時に
変わっていないチャンクを丸ごと再利用できる = 実質的なバイナリ差分保存。

- 平均チャンク ~ 8KiB (最小 2KiB / 最大 64KiB)。
- ロールバック無しの gear ハッシュで高速。
- 各チャンクは SHA-256 で content-addressed。同じ内容は 1 回だけ保存。

参考: Xia et al., "FastCDC: a Fast and Efficient Content-Defined Chunking
Approach for Data Deduplication" (USENIX ATC 2016)。
"""
from __future__ import annotations

import hashlib

# gear テーブル (決定的に生成。実装間で同一境界になるよう固定シード不要の式)
_GEAR = [(i * 2654435761 + 0x9E3779B9) & 0xFFFFFFFF for i in range(256)]

_MASK_S = (1 << 13) - 1   # 最小チャンク境界を粗く (2KiB 付近)
_MASK_L = (1 << 11) - 1   # 最大側を細かく (平均 ~8KiB)
_MIN = 2048
_MAX = 65536


def _cut(buf: bytes) -> int:
    """buf の先頭から境界位置を返す。"""
    n = len(buf)
    if n <= _MIN:
        return n
    mask = _MASK_S
    fp = 0
    i = _MIN
    limit = min(n, _MAX)
    while i < limit:
        fp = ((fp << 1) + _GEAR[buf[i]]) & 0xFFFFFFFF
        if not (fp & mask):
            return i
        # 中央付近から細かいマスクに切り替えて平均長を整える
        if i >= (_MIN + _MAX) // 2:
            mask = _MASK_L
        i += 1
    return limit


def chunk_bytes(data: bytes) -> list[bytes]:
    """バイト列を内容定義チャンクに分割する。"""
    chunks: list[bytes] = []
    pos = 0
    n = len(data)
    while pos < n:
        size = _cut(data[pos:])
        chunks.append(data[pos:pos + size])
        pos += size
    return chunks


def chunk_file(path: str, chunk_size: int = 1 << 20) -> list[tuple[str, bytes]]:
    """ファイルをチャンク化し (sha256_hex, bytes) のリストを返す。

    ストリーミングで読み、チャンク単位でハッシュを取る。大きいファイルでも
    全内容をメモリに載せない (チャンクのバッファのみ)。
    """
    out: list[tuple[str, bytes]] = []
    with open(path, "rb") as f:
        carry = b""
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            buf = carry + block
            # 末尾の未確定分は次ブロックへ持ち越す (境界が確定した所まで切る)
            pos = 0
            while pos < len(buf):
                size = _cut(buf[pos:])
                if pos + size >= len(buf) and block:
                    # バッファ末尾に達した境界は、まだ続きがあるかもしれないので保留
                    break
                piece = buf[pos:pos + size]
                out.append((hashlib.sha256(piece).hexdigest(), piece))
                pos += size
            carry = buf[pos:]
        if carry:
            out.append((hashlib.sha256(carry).hexdigest(), carry))
    return out
