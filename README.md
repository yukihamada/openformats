# openformats — あなたの作品は、あなたの手元に残るか？

> 1 作品 = 1 JSON。音楽も、本も、ラジオも、声も、動画も、製品も、場所も。
> ぜんぶ同じ語彙で、テキストで、あなたの Git の中に。

**結論から。** openformats は、あらゆる創作の「最小単位」を、人間が読める JSON で定義するオープンな仕様です。曲のメタも、ラジオの台本も、本の章も、声の同意も、1 ファイルに構造として残ります。

特定のアプリに閉じ込められない。100 年後も `cat` で読める。

**なぜ作ったか。** あなたが今日つくった曲や記事は、そのアプリがサービスを終えた瞬間に、開けなくなるかもしれません。openformats はその不安への答えです。作品を、あなたの手元のプレーンテキストに戻します。

---

## 30 秒でわかる

```json
{
  "spec_version": "1.0.0",
  "kind": "music",
  "id": "hitotsu-saki-e",
  "title": "ひとつ先へ",
  "provenance": { "human_involvement": "ai-assisted" }
}
```

これだけ。`kind` を変えれば、ラジオにも、本にも、動画にもなります。同じ道具（検証・ハッシュ）が、ぜんぶの作品にそのまま効きます。

> この README の最後に、**この仕組みで作った 3 つの本物の作品**があります。先に飛ばして聴いてもいい。でも、なぜこの設計なのかは、順番に読むと腹に落ちます。

---

## 3 つの約束

- **自由** — 特定ベンダーに縛られない。テキストで読め、`git diff` で意図がわかる。
- **安全** — 声・肖像・土地の権利と同意を、構造として記録する。AI 生成を人間作と偽らない。
- **長期生存** — 100 年後も読める。バイナリ依存ゼロ。

まずは音楽・ラジオ・本の 3 種類から。世界の表現を支える**インフラの一部**を目指しています。

---

## 実際の作品（この仕組みで作った）

| 作品 | 種類 | 中身 | 状態 |
|---|---|---|---|
| **AIが賢くなるほど、なぜ僕らは忙しいのか？** | ラジオ | 本人声ポッドキャスト第1回・8分58秒・出典3本 | [YouTube で公開](https://youtu.be/EGPYDJIyQ4U) |
| **モコの、ひと息AIニュース** | ラジオ | 週次AIニュース3本・5章・79秒 | 音源は非公開（JSON のみ） |
| **ひとつ先へ** | 音楽 | Senteテーマソング・BPM104・F major・2テイク | 音源は非公開（JSON のみ） |

3 作品とも、このリポジトリの `works/` に **実データの JSON** として置いてあります。音声ファイルの SHA-256、出典 URL、制作履歴まで入っています。あわせて作者情報（`yukihamada.person.json`）と作品集（`collection-2026.collection.json`）も同梱しています。作り方の実例として、そのまま読んでください。

```bash
# 本物の作品を検証してみる（先に pip install jsonschema が必要）
python3 tools/validate.py radio/radio.json works/yuki-podcast-001.radio.json
# → OK  works/yuki-podcast-001.radio.json
```

---

## フォーマット一覧（16 種類）

**まずはこの 3 つ。** 音楽なら `music.json`、ラジオなら `radio.json`、本なら `book.json`。残りは用途に応じて。

すべて `core/envelope.json` を継承します。`kind` を変えるだけで、同じ道具が使えます。

| ファイル | kind | 用途 | 主な接続先 |
|---|---|---|---|
| `music.json` | music | 楽曲・作曲 | Suno/MUREKA/DAW |
| `radio.json` | radio | ラジオ・ポッドキャスト | KOE/teai TTS, music |
| `book.json` | book | 本・原稿 (章/ブロック) | PDF/EPUB/音声化 |
| `movie.json` | movie | 動画タイムライン | image/voice/music |
| `voice.json` | voice | ナレーション・声 | KOE/teai TTS |
| `image.json` | image | 画像・ビジュアル | 生成AI/デザイン |
| `article.json` | article | 記事・投稿 | Web/X/note/Zenn |
| `bim.json` | bim | 建築 (bim.house 互換) | bim.house/spec |
| `device.json` | device | IoT・端末・入出力機器 | スマートホーム/制作機材 |
| `land.json` | land | 土地・区画 | bim/event |
| `country.json` | country | 国・地域プロファイル | 世界展開/規制分岐 |
| `event.json` | event | イベント・興行 | land/bim/movie |
| `collection.json` | collection | アルバム/シリーズ | music/movie/book |
| `person.json` | person | 作者・話者・ペルソナ | voice/作品 |
| `place.json` | place | 場所・会場・POI | land/event/media |
| `product.json` | product | 製品・サービス・ブランド | カタログ/作品連携 |

---

## 収録データ

- `works/` — 実作品（ポッドキャスト・ラジオ・楽曲・作者・作品集）。実音声の SHA-256 と出典付き。
- `products/` — Enabler の製品カタログ 61 件 (`*.product.json`)。状態は確認時点を `status` に記録し、未確認は `unknown`。
- `events/` — イベント (`zamna-hawaii-2026.event.json` 等)。
- `places/` — 会場・POI (`echoa-ridge.place.json` 等)。

---

## 使い方（3 コマンド）

```bash
# 0. 依存を入れる（最初に一度だけ）
pip install jsonschema

# 1. 検証 (JSON Schema でチェック)
python3 tools/validate.py music/music.json examples/sample.music.json

# 2. 内容ハッシュを計算して content_hash を埋める
python3 tools/hash.py examples/sample.music.json --write

# 3. 自分の作品を置く
cp examples/sample.music.json works/my-first-song.music.json
```

---

## 設計哲学

<details>
<summary><b>6 つの原則（クリックで開く）</b></summary>

1. **テキスト first** — 人間が読み書きできる。
2. **content-addressed** — 同じ作品 → 同じ SHA-256。バージョン管理は git に任せる。
3. **append-only friendly** — 過去のリビジョンは消えない。制作の歴史が残る。
4. **vendor neutral** — どのエディタ・DAW・レンダラとも変換可能。
5. **来歴を正直に** — `provenance` に AI 生成・素材の出所・変換履歴を記録する。
6. **同意と権利を最優先** — 声・肖像・土地は `consent` / `rights` を必須運用。

</details>

<details>
<summary><b>共通エンベロープの全フィールド（クリックで開く）</b></summary>

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

`signatures`（Ed25519 補助署名）は仕様で定義済み。署名ツールは今後追加予定です。

</details>

<details>
<summary><b>スキーマの正本はどこ？（クリックで開く）</b></summary>

各スキーマの `$id` は `https://openformats.dev/...` を指しますが、このドメインは**まだ公開していません**。現時点の正本は、このリポジトリ内の `core/` と各 `*/` ディレクトリの JSON ファイルです。バリデータは `$id` をリポジトリ内のファイルへ自動で対応づけるので、オフラインでも検証できます。

</details>

---

## ライセンスと参加

- **仕様 (このリポジトリの *.json スキーマ): MIT**
- **各作品**: 作品ごとの `license` フィールドに従う (既定は作者が選ぶ)。

フォーマットはオープンです。改善提案・新しい kind の追加は歓迎します。このリポジトリは実証段階であり、仕様は後方互換を保ちながら育てていきます。

---

## 最後に — 冒頭の問いの答え

最初に「あなたの作品は、あなたの手元に残るか？」と訊きました。

答えは、**残せる**、です。作品を 1 つの JSON にして、あなたの Git に置けば、アプリが消えても、サービスが終わっても、作品はテキストとして残ります。声の同意も、AI を使った事実も、出典も、全部いっしょに。

`works/` に並ぶ本物の作品が、その証拠です。あなたの番です。
