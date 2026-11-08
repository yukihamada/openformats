# バージョニングと非推奨化

## 仕様バージョン (`spec_version`)

- 形式: `MAJOR.MINOR.PATCH`。v1 系は `1.x.y`。
- **MAJOR**: 後方互換を壊す変更 (必須フィールドの追加・削除、列挙値の意味変更、
  `content_hash` アルゴリズムの変更)。新しいスキーマパス (`v2.json`) を追加する。
- **MINOR**: 後方互換な追加 (任意フィールド・列挙値の追加)。
- **PATCH**: 文言・説明・バグ修正。構造は変えない。

スキーマは `<kind>/v1.json` のようにバージョン付きパスで公開する。
破壊的変更は `v2.json` を新設し、`v1.json` は非推奨期間中も残す。

## 非推奨化 (deprecation)

1. 非推奨にするフィールド/kind を `CHANGELOG.md` に記す。
2. 次の MINOR で `"deprecated": true` を description に明記する。
3. 最低 2 つの MINOR リリースを経てから削除する (MAJOR で)。

## content_hash の互換性

`content_hash` のアルゴリズム (§3) は作品の同一性そのもの。変更は MAJOR 扱い。
アルゴリズムを変える場合、旧ハッシュを `hash_chain` に残し、移行ツールを提供する。

## データの互換性

- 既存データは常に `tools/validate.py --all` と `tools/of.py verify` で検証する。
- CI は main への push と PR で、テスト・スキーマ検証・ハッシュ/署名/チェーン検証を
  すべて実行する。赤はマージしない。
