# Changelog

すべての重要な変更を記録する。形式は Keep a Changelog、バージョニングは SemVer。

## [Unreleased]

### Added
- `tools/renderers/koe.py` を teai の正規非同期経路 (quote → generate →
  poll → audio) に書き換え。従来の単発 POST は実 API と噛み合っていなかった。
  `TEAI_API_KEY` / `KOE_VOICE` / `KOE_LANG` / `KOE_SPEED` を使用。
- `works/Moco-News-yukihamada.mp3` — 実際の radio 作品を本人声で音声化した
  実レンダリング (80.7s / 48kHz / 2.1MB / 8cr)。rendition として作品 JSON に
  path・sha256 付きで紐づき、`of.py verify` が全項目 true。
- `tools/export.py` — 作品 JSON を既存標準へ書き出す最初の変換。現時点で
  **schema.org JSON-LD** に対応 (`python3 tools/export.py schema.org <file>`、
  `--out-dir` で一括、`--list` で実装済み/予定を確認)。kind ごとに
  MusicComposition / PodcastEpisode / Book / Movie / Article / Product 等へ写し、
  `content_hash` を `sha256` として残すので元作品を照合できる。回帰テスト追加。
- README / SPEC / LP に「既存標準との関係」を明記。実装済みは schema.org のみ、
  C2PA・MusicXML・OpenTimelineIO・EPUB は未実装であることを正直に記載。

### Changed
- 「オープンな仕様」→「個人仕様（実証段階）」へ表現を修正。外部採用 0 件
  (2026-11-10) を LP・README に明記し、「標準」を名乗るのは採用後とする方針を追加。
- `tools/render.py` が媒体の `path` を記録するよう修正。出力を作品 JSON と
  同じフォルダへ置き、相対 path を rendition に保存する。従来は path 未設定で
  `of.py verify` の rendition 照合が失敗していた。

- `products/` に公開 GitHub リポジトリ 28 件を実データで追加 (61 → 89 件)。
  KOE OSS / Koe-swift / koe-device / koe-wake-train / BuildPeek / Mamori /
  mini-agent-c (Evo) / MU (mu-brand) / mu-mockups / kenchiku-bench /
  shitate-bench / sente-browser / sente-shield / teai-privacy / teai-docs /
  asoview-c / bonding-ai / enablerhq / kumaushi-climate / miseban-ai /
  openclaw-dashboard / openformats / password-rotate-kagi / sakutsu /
  stayflow-care / yakiniku-university / yukihamada.jp / zenn。
  README・GitHub メタデータ・license SPDX を実読して生成。非公開プロジェクトは
  公開リポジトリに含めない。
- `works/` に全 16 kind の実データを充足。未収録だった 3 kind を追加:
  - `works/bim-deterministic-scoring-2026-11.article.json` — teai-blog の実記事
    (bim.house 決定論採点・442 件実測・方式比較) を 71 ブロックで収録、出典 2 件。
  - `works/bim-house-iso-day.image.json` + `works/bim-house-iso-day.png` —
    bim.house の住宅 BIM アイソメ日景 (1201×728)。実体を同梱し SHA-256 一致。
  - `works/macbook-pro-m5-max-2026.device.json` — 制作端末の実測スペック
    (`system_profiler` / `sw_vers`)。
- `works/collection-2026.collection.json` / `works/yukihamada.person.json` に
  動画・記事・画像を追加。
- `bim/v1.json` を bim.house の完全スキーマ (`https://bim.house/spec/v1.json`) と統合。
  `project` (applicant / designer / supervisor / contractor / road_access /
  drainage / ground_investigation / permit / rooms / mep 等)、`elements`
  (IFC クラス・素材・構造)、`audit`、`attachments`、`$defs` (Element / IFCClass /
  Material / Structural / Signature) を収録。共通フィールドは
  `core/envelope/v1.json` を `$ref` で継承する。
- `examples/sample.bim.json`: bim.house 完全スキーマの実例 (project/rooms/mep/
  elements/audit/attachments/署名)。
- `signatures` は openformats の Ed25519 補助署名 (`public_key`/`signature`) と
  bim.house の建築士署名 (`pubkey`/`digest`/`signature`) の両形式を `anyOf` で許容。

### Changed
- `tools/of.py verify` / `core.verify_signatures`: bim.house 形式の署名は
  content_hash と別 basis のため `valid: null` (検証対象外) として扱い、失敗にしない。
- `tests/test_core.py`: 上記に合わせ、署名検証は `valid is not False` で判定。

## [1.1.0] - 2026-11-08

### Added
- `renditions[]`: 媒体化した実体を実ファイルの SHA-256 と生成モデル来歴つきで
  作品に紐づける。`source_rendition` で「良いモデルで声だけ差し替え」の系譜を残す。
- `consent` / `rights` を構造化スキーマ化 (声・肖像・土地の同意を型で表現)。
- `tools/of.py`: hash / keygen / sign / verify / revise / migrate の CLI。
  `migrate` は計画表示のみ (実体の無い rendition を足さない)。実体生成は
  `render.py --migrate-from <sha256>` が行い、sha256 を埋めてから追加する。
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
