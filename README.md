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
  "spec_version": "1.1.0",
  "kind": "music",
  "id": "hitotsu-saki-e",
  "title": "ひとつ先へ",
  "provenance": { "human_involvement": "ai-assisted" }
}
```

これだけ。`kind` を変えれば、ラジオにも、本にも、動画にもなります。同じ道具（検証・ハッシュ・署名・レンダリング）が、ぜんぶの作品にそのまま効きます。

> この README の最後に、**この仕組みで作った 3 つの本物の作品**があります。音源も同梱しているので、そのまま聴けます。でも、なぜこの設計なのかは、順番に読むと腹に落ちます。

---

## 3 つの約束

- **自由** — 特定ベンダーに縛られない。テキストで読め、`git diff` で意図がわかる。
- **安全** — 声・肖像・土地の権利と同意を、構造として記録する。AI 生成を人間作と偽らない。
- **長期生存** — 100 年後も読める。バイナリ依存ゼロ。

まずは音楽・ラジオ・本の 3 種類から。

---

## 「作品が残る」とは、どういうことか

openformats は、作品を **2 つの層** で残します。

- **設計図（JSON）** — メタデータ・台本・歌詞・来歴・同意。軽く、テキストなので Git で永久に残る。これが正本（source of truth）。
- **本体（音声・映像・画像）** — 実ファイル。JSON の `renditions[].path` に場所、`renditions[].sha256` に指紋を記録する。

このリポジトリの `works/` には、**両方**入っています。JSON と音源がそろい、SHA-256 で結びついているので、音源が改ざんされていないことも、JSON が指す音源が本物であることも、誰でも検証できます。

```bash
# 音源の指紋を確認する（JSON の renditions[].sha256 と一致するか）
shasum -a 256 works/takes/take1_full.m4a
# → 627961020ae8f9fc416da064fd3977447a6d24d9f93a9ec5bc9afcd35e795dea
```

大きな音源をリポジトリに入れたくない場合は、JSON だけを Git に置き、`renditions[].path` を自分のストレージ（S3・NAS・外付け）に向けることもできます。指紋さえ合えば、音源がどこにあっても「本物」と確認できます。

---

## 実際の作品（この仕組みで作った・音源も同梱）

3 作品とも、**音源ファイルそのもの**をこのリポジトリの `works/` に入れてあります。JSON と音源の SHA-256 は一致します。ダウンロードして、そのまま聴けます。

| 作品 | 種類 | 中身 | 音源 | JSON |
|---|---|---|---|---|
| **AIが賢くなるほど、なぜ僕らは忙しいのか？** | ラジオ | 本人声ポッドキャスト第1回・8分58秒・出典3本 | [mp3](works/episode-001.mp3) / [m4a](works/episode-001.m4a) ・ [YouTube](https://youtu.be/EGPYDJIyQ4U) | [radio.json](works/yuki-podcast-001.radio.json) |
| **モコの、ひと息AIニュース** | ラジオ | 週次AIニュース3本・5章・79秒 | [wav](works/Moco-News.wav) / [mp4](works/Moco-News.mp4) | [radio.json](works/moco-news-20261009.radio.json) |
| **ひとつ先へ** | 音楽 | Senteテーマソング・BPM104・F major・2テイク | [take1](works/takes/take1_full.m4a) / [take2](works/takes/take2_full.m4a) | [music.json](works/hitotsu-saki-e.music.json) |

JSON には音源の SHA-256 と制作履歴が入り、出典はラジオ 2 作に付いています。あわせて作者情報（[yukihamada.person.json](works/yukihamada.person.json)）と作品集（[collection-2026.collection.json](works/collection-2026.collection.json)）も同梱しています。設計根拠は [works/RESEARCH.md](works/RESEARCH.md)。

### 音源が本物か、自分で確かめる

```bash
# JSON に記録した SHA-256 と、実ファイルのハッシュが一致するか
shasum -a 256 works/episode-001.mp3
# → cbd512aa79f9a819f38ed6a5c6d2064e451365dbd88283c96a146964652a1e4e
```

この値は [yuki-podcast-001.radio.json](works/yuki-podcast-001.radio.json) の `renditions[].sha256` と同じです。ハッシュが一致すれば、その音源は改ざんされていない本物です。

### JSON も検証できる

```bash
# 依存は「使い方」の venv 手順で導入済みならそのまま実行できる
python3 tools/validate.py radio/v1.json works/yuki-podcast-001.radio.json
# → OK  works/yuki-podcast-001.radio.json
```

---

## フォーマット一覧（16 種類）

**まずはこの 3 つ。** 音楽なら [music/v1.json](music/v1.json)、ラジオなら [radio/v1.json](radio/v1.json)、本なら [book/v1.json](book/v1.json)。残りは用途に応じて。

すべて [core/envelope/v1.json](core/envelope/v1.json) を継承します。`kind` を変えるだけで、同じ道具が使えます。

| スキーマ | kind | 用途 | 主な接続先 |
|---|---|---|---|
| [music/v1.json](music/v1.json) | music | 楽曲・作曲 | Suno/MUREKA/DAW |
| [radio/v1.json](radio/v1.json) | radio | ラジオ・ポッドキャスト | KOE/teai TTS, music |
| [book/v1.json](book/v1.json) | book | 本・原稿 (章/ブロック) | PDF/EPUB/音声化 |
| [movie/v1.json](movie/v1.json) | movie | 動画タイムライン | image/voice/music |
| [voice/v1.json](voice/v1.json) | voice | ナレーション・声 | KOE/teai TTS |
| [image/v1.json](image/v1.json) | image | 画像・ビジュアル | 生成AI/デザイン |
| [article/v1.json](article/v1.json) | article | 記事・投稿 | Web/X/note/Zenn |
| [bim/v1.json](bim/v1.json) | bim | 建築 (bim.house 完全スキーマ統合) | bim.house/spec |
| [device/v1.json](device/v1.json) | device | IoT・端末・入出力機器 | スマートホーム/制作機材 |
| [land/v1.json](land/v1.json) | land | 土地・区画 | bim/event |
| [country/v1.json](country/v1.json) | country | 国・地域プロファイル | 世界展開/規制分岐 |
| [event/v1.json](event/v1.json) | event | イベント・興行 | land/bim/movie |
| [collection/v1.json](collection/v1.json) | collection | アルバム/シリーズ | music/movie/book |
| [person/v1.json](person/v1.json) | person | 作者・話者・ペルソナ | voice/作品 |
| [place/v1.json](place/v1.json) | place | 場所・会場・POI | land/event/media |
| [product/v1.json](product/v1.json) | product | 製品・サービス・ブランド | カタログ/作品連携 |

---

## 収録データ

- [works/](works/) — 実作品（ポッドキャスト・ラジオ・楽曲・作者・作品集）。**音源ファイル本体も同梱**、JSON の SHA-256 と一致。
- [products/](products/) — Enabler の製品カタログ 61 件 (`*.product.json`)。状態は確認時点を `status` に記録し、未確認は `unknown`。
- [events/](events/) — イベント（[zamna-hawaii-2026.event.json](events/zamna-hawaii-2026.event.json) 等）。
- [places/](places/) — 会場・POI（[echoa-ridge.place.json](places/echoa-ridge.place.json) 等）。
- [examples/](examples/) — 各フォーマットの最小サンプル。自分の作品を作るときは署名なし・`renditions` 付きの [templates/starter.music.json](templates/starter.music.json) をコピーすると最短です（`sha256` は空なので、`validate` の前に `hash --write` を実行してください）。建築は [examples/sample.bim.json](examples/sample.bim.json)（bim.house 完全スキーマの実例）。

---

## この JSON を使うプロダクト

各フォーマット（kind）を**実際に生成・消費する**プロダクトだけを載せています（カタログ全件は [products/](products/)）。業務ツールや会社ページなど、対応する kind を持たないものはここには含めていません。

**voice / radio / music / movie / image** — 声・音楽・映像
- [KOE](https://koe.live) — 登録済みの声から音声アセットを生成（voice）
- [KOE 音声入力](https://app.koe.live) ・ [声メッセンジャー MCP](https://mcp.koe.live) ・ [say.koe](https://say.koe.live)
- [uta.live](https://uta.live) ・ [movie.live](https://movie.live) ・ [news.xyz](https://news.xyz) ・ [Soluna Live Radio](https://apps.apple.com/jp/app/id6759962263)
- [kamishibai.tv](https://kamishibai.tv) ・ [紙芝居KOE](https://kamishibai-koe.pages.dev)

**bim / land / place / event** — 建築・土地・滞在
- [bim.house](https://bim.house) — 建築情報モデルと申請準備データ（bim）
- [ZUMEN.HOUSE](https://zumen.house) ・ [KATA.HOUSE](https://kata.house) ・ [MU HOUSE](https://house.wearmu.com) ・ [1HOUR.HOUSE](https://1hour.house)
- [SOLUNA](https://solun.art) ・ [StayFlow](https://stayflowapp.com/stays) ・ [enabler.fun](https://enabler.fun)

**image / collection** — デザイン・商品
- [MU](https://wearmu.com/make) — 言葉から服・グッズのデザイン（image）
- [MU MART](https://mart.wearmu.com) ・ [Takara Market](https://takaramarket.com) ・ [chatbuy](https://chatbuy.pages.dev)

**article / event** — 学び・コミュニティ
- [JiuFlow](https://jiuflow.com) ・ [WeGoFast](https://wegofast.app) ・ [焚き火 / ATSM](https://takibi.wtf) ・ [焚き火の紙芝居](https://takibi-story.pages.dev)

**article / book** — AI・制作
- [teai](https://teai.io) ・ [先手 / Sente](https://sente.teai.io) ・ [Elio](https://elio.love) ・ [Trio](https://trio.fly.dev)
- [chatweb.ai](https://chatweb.ai) ・ [NOU](https://nou.fund) ・ [Kata（AI）](https://kata-ai.fly.dev) ・ [OpenClaw](https://github.com/yukihamada/openclaw)

---

## 使い方（3 つのツール・4 ステップ）

```bash
# 0. 依存を入れる（最初に一度だけ）
python3 -m venv .venv
source .venv/bin/activate          # venv に入る（以降 python3 は venv の Python）
pip install jsonschema

# 1. 検証 — JSON Schema で作品をチェック
python3 tools/validate.py music/v1.json examples/sample.music.json
python3 tools/validate.py --all          # 全サンプル・作品・カタログを一括検証

# 2. ハッシュ — 内容の SHA-256 を計算し content_hash に書き込む
#    renditions[].path の実体があれば、その sha256 も自動で充填する
python3 tools/of.py hash examples/sample.music.json --write

# 3. 署名 — Ed25519 で content_hash に補助署名し、検証する
python3 tools/of.py keygen --key-out ~/.openformats/secret.b64
cp works/hitotsu-saki-e.music.json works/try.music.json   # 同じフォルダ内に複製（renditions の相対パスを保つ）
python3 tools/of.py sign works/try.music.json --key ~/.openformats/secret.b64 --signer yuki --write
python3 tools/of.py verify works/try.music.json
rm works/try.music.json

# 4. レンダリング — JSON から媒体を作り、SHA-256 で作品に紐づける
python3 tools/render.py examples/sample.music.json --kind audio --format wav --dry-run
```

> `source .venv/bin/activate` を使わない場合は、各コマンドの `python3` を `.venv/bin/python` に置き換えれば同じです。

使うツールはこの 3 つです。

- [tools/validate.py](tools/validate.py) — JSON Schema (Draft 2020-12) で作品を検証する。`--all` でリポジトリ全体。
- [tools/of.py](tools/of.py) — ハッシュ・Ed25519 署名・検証・改訂（`revise`）・モデル移行（`migrate`）の CLI。`verify` は `content_hash`・署名・チェーンに加え、`renditions[].path` の実体存在と SHA-256 一致まで検証する（音源が欠けていれば `ok: false`）。
- [tools/render.py](tools/render.py) — JSON を媒体化し、実体の SHA-256 で作品に紐づける（`--dry-run` で安全に試せる）。

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
  "$schema": "https://yukihamada.github.io/openformats/core/envelope/v1.json",
  "spec_version": "1.1.0",
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

`signatures`（Ed25519 補助署名）は仕様で定義済みで、[tools/of.py](tools/of.py) の `sign` / `verify` で実際に使えます。

</details>

<details>
<summary><b>スキーマの正本はどこ？（クリックで開く）</b></summary>

各スキーマの `$id` は `https://yukihamada.github.io/openformats/...`（GitHub Pages）を指し、**公開されています**。バリデータはこの URL をリポジトリ内の実ファイルへローカル解決するので、ネットワークなしでも検証できます。仕様の規範文書は [SPEC.md](SPEC.md)、版管理の方針は [VERSIONING.md](VERSIONING.md)、変更履歴は [CHANGELOG.md](CHANGELOG.md) を参照してください。

</details>

---

## ライセンスと参加

- **仕様 (このリポジトリの *.json スキーマ): MIT** — [LICENSE](LICENSE)
- **各作品**: 作品ごとの `license` フィールドに従う (既定は作者が選ぶ)。

フォーマットはオープンです。改善提案・新しい kind の追加は歓迎します。このリポジトリは実証段階であり、仕様は後方互換を保ちながら育てていきます。参加方法は [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 最後に — 冒頭の問いの答え

最初に「あなたの作品は、あなたの手元に残るか？」と訊きました。

答えは、**残せる**、です。作品を 1 つの JSON にして、あなたの Git に置けば、設計図・歌詞・来歴・同意はテキストとして残ります。音声や映像の本体も、このリポジトリのように同梱するか手元に置き、JSON の SHA-256 で照合できます。アプリが消えても、サービスが終わっても、作品はあなたの手元に残ります。

`works/` に並ぶ本物の作品と、その音源が、その証拠です。あなたの番です。
