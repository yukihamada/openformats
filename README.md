# openformats — メディアの最小単位を、みんなの手に

> 1 作品 = 1 JSON。JSON が正本。
> アプリやモデルで媒体化したものは、ハッシュで作品に紐づける。
> 同じ作品は同じハッシュ。良いモデルが出たら、作品はそのまま声だけ差し替える。

音楽・本・動画・ラジオ・声・画像・土地・イベントを、同じ語彙で。
content-addressed、append-only、Ed25519 補助署名、MIT。

## 何を解くか

人は表現したい。だがその手段は、巨大なアプリの中に閉じ込められてきた。

openformats は、あらゆる創作の「最小単位」をオープンな JSON で定義し、
誰もが自分の作品を、自分の手元で、自由に、安全に管理できるようにする。

- **自由** — 特定ベンダーに縛られない。テキストで読め、`git diff` で意図がわかる。
- **安全** — 声・肖像・土地の権利と同意を構造として記録する。AI 生成を人間作と偽らない。
- **接続** — teai / KOE / Suno / MUREKA / bim.house などの AI と組み合わせれば、
  1 つの JSON から音楽も、本も、動画も、ラジオも生まれる。
- **長期生存** — 100 年後も読める。JSON と標準ライブラリだけで完結する。

## 中心にある考え方

```
作品 (work JSON)  ── 正本。content_hash が作品の同一性を決める
   │
   ├─ renditions[]  媒体化した実体 (音声/動画/画像/PDF)
   │                   実ファイルの SHA-256 と生成モデルの来歴を持つ
   │                   source_rendition で「どの版から派生したか」を系譜化
   │
   ├─ hash_chain[]  その作品が持った content_hash の全履歴 (バージョン管理)
   └─ signatures[]  content_hash への Ed25519 補助署名
```

- **媒体化しても作品は変わらない。** `renditions` は `content_hash` の対象外。
  音声を作っても、動画を作っても、作品のハッシュは同じ。
- **良いモデルが出たら、声だけ差し替える。** 新しい `rendition` を足し、
  `source_rendition` に派生元を記録する。`content_hash` は不変 = 同じ作品。
- **創作内容を変えたときだけ、ハッシュが変わる。** 歌詞・構成・本文の編集は
  `content_hash` を変え、`hash_chain` に新しい版として積まれる。
- **来歴は正直に。** AI 生成・素材の出所・生成モデル・プロンプトを記録する。

## 使い方

```bash
pip install jsonschema          # 検証のみ外部依存

# スキーマ検証 (全データ)
python3 tools/validate.py --all

# content_hash を計算して埋める
python3 tools/of.py hash examples/sample.music.json --write

# 鍵生成・署名・検証
python3 tools/of.py keygen --key-out ~/.openformats/secret.b64
python3 tools/of.py sign examples/sample.music.json --key ~/.openformats/secret.b64 --signer yuki --write
python3 tools/of.py verify examples/sample.music.json

# JSON を媒体化 → 内容アドレス保存 → 作品に紐づけ (ドライラン)
python3 tools/render.py examples/sample.music.json --kind audio --format wav --dry-run --write

# 良いモデルで声だけ差し替え (content_hash は不変)
python3 tools/render.py work.json --renderer koe --kind audio --format mp3 \
    --model koe-v3 --migrate-from <prev-rendition-sha256> --write

# 改訂を積む (hash_chain に新 head)
python3 tools/of.py revise work.json --action edit --by yuki --note "歌詞修正" --write
```

## フォーマット一覧

| ファイル | kind | 用途 | 主な変換先 |
|---|---|---|---|
| `book/v1.json` | book | 本・原稿 (章/ブロック) | PDF / EPUB / 音声化 |
| `bim/v1.json` | bim | 建築 (bim.house 互換) | bim.house/spec |
| `device/v1.json` | device | IoT・端末・入出力機器 | スマートホーム/制作機材 |
| `radio/v1.json` | radio | ラジオ・ポッドキャスト | KOE/teai TTS, music |
| `movie/v1.json` | movie | 動画タイムライン | image/voice/music, ffmpeg |
| `music/v1.json` | music | 楽曲・作曲 | Suno/MUREKA/DAW |
| `voice/v1.json` | voice | ナレーション・声 | KOE/teai TTS |
| `image/v1.json` | image | 画像・ビジュアル | 生成AI/デザイン |
| `article/v1.json` | article | 記事・投稿 | Web/X/note/Zenn |
| `land/v1.json` | land | 土地・区画 | bim/event |
| `country/v1.json` | country | 国・地域プロファイル | 世界展開/規制分岐 |
| `event/v1.json` | event | イベント・興行 | land/bim/movie |
| `collection/v1.json` | collection | アルバム/プレイリスト/シリーズ | music/movie/book |
| `person/v1.json` | person | 作者・話者・ペルソナ | voice/作品 |
| `place/v1.json` | place | 場所・会場・POI | land/event/media |
| `product/v1.json` | product | 製品・サービス・ブランド | カタログ/作品連携 |

すべて `core/envelope/v1.json` を継承する。スキーマは
`https://yukihamada.github.io/openformats/<kind>/v1.json` で解決できる。

## 収録データ

- `examples/` — 各 kind のサンプル (署名済み・content_hash 付き)。
- `products/` — 製品カタログ (`*.product.json`)。状態は `status` に記録。
- `events/`, `places/` — イベント・会場。

> 現状は「仕様 + サンプル + カタログ」の実証段階です。実作品の蓄積と、
> 各 kind のサンプル拡充を進めています。誇張しません。

## 検証と準拠

```bash
python3 tests/test_core.py       # 正規化・署名・ハッシュ・チェーン・移行 (11 件)
python3 tools/validate.py --all  # 全データのスキーマ検証
python3 tools/of.py verify <file>  # content_hash / 署名 / hash_chain
```

CI (`.github/workflows/validate.yml`) が push と PR で上記をすべて実行する。

## 仕様

- [SPEC.md](SPEC.md) — 規範仕様 (content_hash アルゴリズム、rendition、同意・権利)。
- [VERSIONING.md](VERSIONING.md) — バージョニングと非推奨化。
- [CHANGELOG.md](CHANGELOG.md) — 変更履歴。
- [CONTRIBUTING.md](CONTRIBUTING.md) — 参加方法。

## ライセンス

- **仕様 (このリポジトリの `*.json` スキーマとツール): MIT**
- **各作品**: 作品ごとの `license` フィールドに従う。
