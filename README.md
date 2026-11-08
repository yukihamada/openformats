# openformats — メディアの最小単位を、みんなの手に

> 1 作品 = 1 JSON。content-addressed、append-only、Ed25519 補助署名、MIT。
> 音楽・本・動画・ラジオ・声・画像・土地・イベントを、同じ語彙で自由に、安全に。

## ミッション

人は、表現したい。だがその手段は、巨大なアプリの中に閉じ込められてきた。
**openformats** は、あらゆる創作の「最小単位」をオープンな JSON で定義し、
誰もが自分の作品を、自分の手元で、自由に、安全に管理できるようにする。

- **自由** — 特定ベンダーに縛られない。テキストで読め、`git diff` で意図がわかる。
- **安全** — 声・肖像・土地の権利と同意を、構造として記録する。AI 生成を人間作と偽らない。
- **接続** — teai / KOE / Suno / MUREKA / bim.house などの AI と組み合わせれば、
  1 つの JSON から音楽も、本も、動画も、ラジオも生まれる。
- **長期生存** — 100 年後も読める。バイナリ依存ゼロ。

私たちは、世界の表現を支える**インフラの一部**になることを目指す。

## 設計哲学 (bim.json v1 から継承)

1. **テキスト first** — 人間が読み書きできる。
2. **content-addressed** — 同じ作品 → 同じ SHA-256。バージョン管理は git に任せる。
3. **append-only friendly** — 過去のリビジョンは消えない。制作の歴史が残る。
4. **vendor neutral** — どのエディタ・DAW・レンダラとも変換可能。
5. **来歴を正直に** — `provenance` に AI 生成・素材の出所・変換履歴を記録する。
6. **同意と権利を最優先** — 声・肖像・土地は `consent` / `rights` を必須運用。

## フォーマット一覧

| ファイル | kind | 用途 | 主な接続先 |
|---|---|---|---|
| `book.json` | book | 本・原稿 (章/ブロック) | PDF/EPUB/音声化 |
| `bim.json` | bim | 建築 (bim.house 互換) | bim.house/spec |
| `device.json` | device | IoT・端末・入出力機器 | スマートホーム/制作機材 |
| `radio.json` | radio | ラジオ・ポッドキャスト | KOE/teai TTS, music |
| `movie.json` | movie | 動画タイムライン | image/voice/music |
| `music.json` | music | 楽曲・作曲 | Suno/MUREKA/DAW |
| `voice.json` | voice | ナレーション・声 | KOE/teai TTS |
| `image.json` | image | 画像・ビジュアル | 生成AI/デザイン |
| `article.json` | article | 記事・投稿 | Web/X/note/Zenn |
| `land.json` | land | 土地・区画 | bim/event |
| `country.json` | country | 国・地域プロファイル | 世界展開/規制分岐 |
| `event.json` | event | イベント・興行 | land/bim/movie |
| `collection.json` | collection | アルバム/プレイリスト/シリーズ | music/movie/book |
| `person.json` | person | 作者・話者・ペルソナ | voice/作品 |
| `place.json` | place | 場所・会場・POI | land/event/media |

すべて `core/envelope.json` を継承する。

## 共通エンベロープ (`core/envelope.json`)

```json
{
  "$schema": "https://openformats.dev/core/envelope/v1.json",
  "spec_version": "1.0.0",
  "kind": "music",
  "id": "my-first-song",
  "title": "はじまりの歌",
  "lang": "ja",
  "license": "CC-BY-4.0",
  "provenance": {
    "generator": { "name": "teai", "version": "2026.11" },
    "human_involvement": "ai-assisted",
    "history": [{ "at": "2026-11-08T00:00:00Z", "action": "create", "by": "yuki" }]
  },
  "content_hash": "…64 hex…",
  "signatures": [{ "alg": "Ed25519", "public_key": "…", "signature": "…" }],
  "access": { "visibility": "public", "derivatives": "allow" }
}
```

## 使い方

```bash
# 検証 (JSON Schema でチェック)
python3 tools/validate.py music/music.json examples/sample.music.json

# 内容ハッシュを計算して content_hash を埋める
python3 tools/hash.py examples/sample.music.json --write
```

## ライセンス

- **仕様 (このリポジトリの *.json スキーマ): MIT**
- **各作品**: 作品ごとの `license` フィールドに従う (既定は作者が選ぶ)。

## 参加

フォーマットはオープンです。改善提案・新しい kind の追加は歓迎します。
このリポジトリは実証段階であり、仕様は後方互換を保ちながら育てていきます。
