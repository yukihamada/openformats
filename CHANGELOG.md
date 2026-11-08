# Changelog

すべての重要な変更を記録する。形式は Keep a Changelog、バージョニングは SemVer。

## [1.1.0] - 2026-11-08

### Added
- `renditions[]`: 媒体化した実体を実ファイルの SHA-256 と生成モデル来歴つきで
  作品に紐づける。`source_rendition` で「良いモデルで声だけ差し替え」の系譜を残す。
- `consent` / `rights` を構造化スキーマ化 (声・肖像・土地の同意を型で表現)。
- `tools/of.py`: hash / keygen / sign / verify / revise / migrate の CLI。
- `tools/render.py`: JSON → 媒体 → 内容アドレス保存 (`.ofstore/<sha256>`) の
  パイプライン。`--dry-run` と `--migrate-from` に対応。
- `tools/renderers/koe.py`: KOE/teai TTS レンダラの実装例。
- `tools/openformats/`: JCS(RFC 8785) 正規化、純 Python Ed25519、コアライブラリ。
- `tests/test_core.py`: 正規化・署名・ハッシュ・チェーン・移行の回帰テスト (11 件)。
- `.github/workflows/validate.yml`: テスト + スキーマ検証 + ハッシュ/署名検証の CI。
- `SPEC.md` / `VERSIONING.md` / `CONTRIBUTING.md`。

### Changed
- **content_hash を JCS (RFC 8785) に固定**。数値・文字列・キー順序を正規化し、
  実装間でハッシュが一致するようにした。
- **content_hash の対象から `renditions` と `provenance.history` を除外**。
  これにより媒体化・声の差し替え・改訂記録で作品の同一性 (ハッシュ) が不変になる。
- `hash_chain` を「現在の頭まで含む全履歴」に統一。検証規則を明確化。
- スキーマを `<kind>/v1.json` のバージョン付きパスへ移動。
- `$id` / `$ref` / `$schema` を実在ホスト `https://yukihamada.github.io/openformats/`
  に変更 (旧 `openformats.dev` は DNS 未解決で全スキーマが壊れていた)。
- `tools/validate.py` に `--all` を追加。`$ref` をネットワーク不要でローカル解決。

### Fixed
- 全データ 68 ファイルに `content_hash` を付与 (以前は 0 件)。
- 5 つのサンプルに Ed25519 署名を付与し、検証可能にした。
- スキーマの列挙値 (`human_involvement`, `consent.status` 等) が実際に検証される
  ことをテストで確認。

### Removed
- `tools/hash.py` (`tools/of.py hash` に統合)。

## [1.0.0] - 2026-11-08

### Added
- 初版。16 kind のスキーマ、共通エンベロープ、サンプル、製品カタログ。
