"""content-addressed オブジェクトストア。外部依存ゼロ。

バイナリ実体を「内容の SHA-256」で保存する。同じ内容は 1 回だけ置かれ、
チャンク化と組み合わせると「変わった部分だけ保存」になる。ローカル実装は
ディレクトリ (.ofstore/)。同じインターフェースで S3/R2 等に差し替え可能。

レイアウト:
    <root>/objects/<sha[:2]>/<sha>        実体 (バイト列)
    <root>/manifests/<sha>.json           チャンク目録 (大きいメディア用)

課金メータリングのため、保存バイト数 (ユニーク) と論理バイト数を分けて数える。
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib

from . import chunking


class Store:
    def __init__(self, root: str):
        self.root = pathlib.Path(root)
        self.objects = self.root / "objects"
        self.manifests = self.root / "manifests"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.manifests.mkdir(parents=True, exist_ok=True)

    # --- 単一オブジェクト -------------------------------------------------
    def _obj_path(self, sha: str) -> pathlib.Path:
        return self.objects / sha[:2] / sha

    def has(self, sha: str) -> bool:
        return self._obj_path(sha).exists()

    def put_bytes(self, data: bytes) -> tuple[str, int]:
        """バイト列を保存し (sha256, 新規に書いたバイト数) を返す。"""
        sha = hashlib.sha256(data).hexdigest()
        p = self._obj_path(sha)
        if p.exists():
            return sha, 0
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)
        return sha, len(data)

    def get_bytes(self, sha: str) -> bytes:
        return self._obj_path(sha).read_bytes()

    # --- チャンク化して保存 ----------------------------------------------
    def put_file_chunked(self, path: str) -> dict:
        """ファイルをチャンク化して保存。目録を返す。

        戻り値:
            {"sha256": 全体ハッシュ, "bytes": 論理サイズ,
             "chunks": [sha...], "manifest_sha256": 目録ハッシュ,
             "new_bytes": 実際に新規保存したバイト数}
        """
        chunks = chunking.chunk_file(path)
        shas = []
        new_bytes = 0
        total = 0
        whole = hashlib.sha256()
        for csha, piece in chunks:
            s, written = self.put_bytes(piece)
            shas.append(s)
            new_bytes += written
            total += len(piece)
            whole.update(piece)
        manifest = {
            "chunks": shas,
            "bytes": total,
            "chunk_count": len(shas),
            "sha256": whole.hexdigest(),
        }
        mbytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        msha = hashlib.sha256(mbytes).hexdigest()
        mp = self.manifests / f"{msha}.json"
        if not mp.exists():
            mp.write_bytes(mbytes)
        manifest["manifest_sha256"] = msha
        manifest["new_bytes"] = new_bytes
        return manifest

    def get_manifest(self, msha: str) -> dict:
        return json.loads((self.manifests / f"{msha}.json").read_text())

    def reassemble(self, msha: str) -> bytes:
        """目録から元のバイト列を復元する。"""
        m = self.get_manifest(msha)
        return b"".join(self.get_bytes(s) for s in m["chunks"])

    def materialize(self, msha: str, out_path: str) -> str:
        """目録から実体をファイルへ書き出す。全体ハッシュを返す。"""
        data = self.reassemble(msha)
        pathlib.Path(out_path).write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    # --- 採算メータリング -------------------------------------------------
    def usage(self) -> dict:
        """保存済みのユニークバイト数・オブジェクト数・目録数を返す。"""
        n_obj = 0
        n_bytes = 0
        for p in self.objects.rglob("*"):
            if p.is_file() and not p.name.endswith(".tmp"):
                n_obj += 1
                n_bytes += p.stat().st_size
        n_man = sum(1 for _ in self.manifests.glob("*.json"))
        return {"objects": n_obj, "unique_bytes": n_bytes, "manifests": n_man}
