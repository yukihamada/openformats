# 参加する

openformats はオープンです。バグ・提案・新しい kind を歓迎します。

## 開発環境

```bash
pip install jsonschema
python3 tests/test_core.py          # コアの回帰テスト
python3 tools/validate.py --all     # 全データのスキーマ検証
```

外部依存は `jsonschema` のみ (検証時)。ハッシュ・署名・正規化は標準ライブラリと
同梱の Ed25519 実装だけで動く。

## 変更の流れ

1. ブランチを切る。
2. 変更する。
3. ローカルで通す:
   ```bash
   python3 tests/test_core.py
   python3 tools/validate.py --all
   for f in examples products events places; do
     for j in $(find $f -name '*.json'); do python3 tools/of.py verify "$j"; done
   done
   ```
4. PR を出す。CI が緑になってからマージする。

## スキーマを変えるとき

- 後方互換な追加は MINOR。破壊的変更は新しい `v2.json` を新設 (VERSIONING.md)。
- 列挙値を増やすときは、既存値の意味を変えない。
- `consent` / `rights` を緩めない (安全側に倒す)。

## 新しい kind を足すとき

1. `<kind>/v1.json` を作り、`core/envelope/v1.json` を `allOf` で継承する。
2. `$id` を `https://yukihamada.github.io/openformats/<kind>/v1.json` にする。
3. `kind` を envelope の `enum` に追加する。
4. `examples/sample.<kind>.json` を 1 つ以上足す。
5. `tools/validate.py --all` が通ることを確認する。

## データを足すとき

- `content_hash` を必ず埋める: `python3 tools/of.py hash <file> --write`。
- 公開データは署名を推奨: `python3 tools/of.py sign <file> --key <secret> --write`。
- 秘密鍵をコミットしない。公開鍵だけ `keys/` に置く。

## 行動規範

- 事実と推測を分ける。未確認を確認済みと書かない。
- 声・肖像・土地の権利と同意を尊重する。同意なき生成をしない。
- AI 生成を人間作と偽らない (`provenance.human_involvement`)。
