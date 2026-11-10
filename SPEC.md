# openformats 仕様 (v1)

> 1 作品 = 1 JSON。JSON が正本。媒体はハッシュで作品に紐づく。
> 同じ作品は同じハッシュ。良いモデルが出たら、作品はそのまま声だけ差し替える。

この文書は規範 (normative) です。キーワード「必須」「任意」「してはならない」は
RFC 2119 に従います。

## 1. モデル

```
作品 (work JSON)  ── 正本。content_hash で同一性を表す
   │
   ├─ renditions[]  媒体化した実体 (音声/動画/画像/PDF)。実体の SHA-256 を持つ
   │      └─ source_rendition で「どの rendition から派生したか」を系譜化
   │
   ├─ provenance.history[]  運用ログ (append-only)
   ├─ hash_chain[]          その作品が持った content_hash の全履歴
   └─ signatures[]          content_hash への Ed25519 補助署名
```

- **正本は JSON**。音声・動画・画像は派生物 (rendition) であり、作品の同一性は
  `content_hash` が決める。
- **モデル移行**とは、作品の `content_hash` を変えずに、新しい `rendition` を
  追加すること。`source_rendition` に派生元の SHA-256 を入れて系譜を残す。

## 2. エンベロープ (全 kind 共通)

正本スキーマ: `core/envelope/v1.json`
`$id`: `https://yukihamada.github.io/openformats/core/envelope/v1.json`

必須: `spec_version`, `kind`, `id`。

| フィールド | 必須 | 説明 |
|---|---|---|
| `spec_version` | ✓ | `1.x.y`。準拠する仕様バージョン。 |
| `kind` | ✓ | フォーマット種別 (下記)。 |
| `id` | ✓ | `^[a-z0-9][a-z0-9-]{0,63}$` の安定スラッグ。 |
| `title` | | 表示タイトル。 |
| `lang` | | BCP-47。 |
| `license` | | SPDX 推奨。 |
| `authors[]` | | 作者 (人間・AI 可)。 |
| `provenance` | | 来歴。`human_involvement` は列挙値のみ。 |
| `consent` | | 声・肖像・土地の同意 (構造化)。 |
| `rights` | | 著作権・原盤権・商標 (構造化)。 |
| `content_hash` | | 本体の JCS-SHA256 (下記 §3)。 |
| `hash_chain[]` | | 全 head 履歴 (下記 §5)。 |
| `signatures[]` | | content_hash への Ed25519 署名 (§4)。 |
| `renditions[]` | | 媒体実体と来歴 (§6)。 |
| `access` | | 公開範囲・派生物可否。 |

### kind 一覧

`book, device, radio, movie, music, land, country, image, voice, article, event, bim, collection, person, place, product`

各 kind のスキーマは `<kind>/v1.json`。すべて envelope を `allOf` で継承する。

## 3. content_hash (必須アルゴリズム)

`content_hash` = `SHA-256( JCS( 本体 ) )` の hex (小文字 64 桁)。

- **JCS**: RFC 8785 JSON Canonicalization Scheme。
  - オブジェクトキーは UTF-16 コードユニット順。
  - 数値は ECMAScript `Number::toString` (実装: `tools/openformats/canonical.py`)。
  - 文字列は ECMAScript `JSON.stringify` エスケープ。
  - 空白なし・UTF-8。
- **本体 (hashed body)**: 作品 JSON から次を除いたもの。
  - `content_hash` (自身)
  - `signatures` (署名)
  - `hash_chain` (履歴)
  - `renditions` (媒体出力)
  - `provenance.history` (運用ログ)

この除外により、次が保証される:

- 媒体化しても `content_hash` は不変。
- 良いモデルで声だけ差し替えても `content_hash` は不変 (= 作品の同一性)。
- 歌詞・構成など**創作内容**を変えたときだけ `content_hash` が変わる。

## 4. 署名 (任意・補助)

- アルゴリズム: Ed25519 (RFC 8032)。
- 署名対象: `content_hash` の 32 バイト (hex を `bytes.fromhex` したもの)。
- `signatures[]` の各要素: `alg`(=`"Ed25519"`), `public_key`(base64 32B),
  `signature`(base64 64B), `signer`, `signed_at`。
- 同一 `public_key` の既存署名は置換する。
- これは**補助署名**であり法的正本ではない。電子署名法 3 条認定 CA 等と併用する。

検証: `python3 tools/of.py verify work.json`。

## 5. バージョン管理 (hash_chain)

- `hash_chain[]` は、その作品がこれまでに持った `content_hash` の**順序付き全履歴**
  (現在の頭を含む)。append-only。過去要素は削除してはならない。
- 内容を編集したら `tools/of.py revise` で新しい頭を積む。
- 検証規則:
  - チェーンが空でなければ、末尾 == 現在の `content_hash` (巻き戻し検知)。
  - `sha256` に重複がない (履歴の単調性)。
- 過去の本文そのものは git 履歴が保持する。`hash_chain` は「どの版が存在したか」を
  軽量に示す。

## 6. renditions (媒体化と来歴)

`renditions[]` の各要素:

| フィールド | 必須 | 説明 |
|---|---|---|
| `kind` | ✓ | media 種別 (audio/video/image/pdf/midi/stem …)。 |
| `format` | ✓ | ファイル形式。 |
| `sha256` | ✓ | 媒体実体の SHA-256 (hex 64)。 |
| `bytes` | | サイズ。 |
| `path` | | 保存先 (内容アドレスなら `.ofstore/<sha256>`)。 |
| `provider` | | 生成サービス (koe/teai/suno/mureka …)。 |
| `model` | | 生成モデル名。 |
| `model_version` | | モデルの版。 |
| `prompt` | | 生成プロンプト。 |
| `seed` | | 乱数種。 |
| `voice` | | 声 id (voice.json 参照)。 |
| `source_rendition` | | 派生元 rendition の sha256 (系譜)。 |
| `generated_at` | | 生成時刻。 |

媒体実体は内容アドレスで保存する (`tools/render.py` は `.ofstore/<sha256>`)。
同じ実体は重複保存しない。

## 7. 同意と権利 (構造化)

- `consent`: `subject`, `status`(`granted/pending/revoked/not-required/unknown`),
  `scope[]`, `ai_generation_allowed`, `granted_by`, `granted_at`, `expires_at`,
  `evidence`。
- `rights`: `copyright_holder`, `master_holder`, `composition_holder`,
  `sample_clearance`, `trademark[]`, `notes`。
- 声・肖像・土地を扱う作品は `consent` を記録することが**強く推奨**される。
  未確認を `granted` と偽ってはならない (`status: unknown` を使う)。

## 8. 準拠 (conformance)

ある JSON が v1 に**準拠**するとは:

1. 対応する `<kind>/v1.json` でスキーマ検証に通る。
2. `content_hash` が §3 のアルゴリズムで再計算した値と一致する。
3. `hash_chain` が §5 の検証規則を満たす。
4. `signatures[]` がある場合、openformats の Ed25519 補助署名 (`public_key`) は
   すべて検証に通る。bim.house の建築士署名 (`pubkey`/`digest`) は content_hash
   と別 basis に署名するため、openformats では検証対象外 (`valid: null`) として
   扱い、失敗にしない。

検証コマンド: `python3 tools/validate.py --all && python3 tools/of.py verify <file>`。

## 9. 既存標準との関係

openformats は既存標準を置き換えず、それらへの**ハブ**を目指す。

> **実装状況（2026-11-11）**: 実装済みの変換は **schema.org（往復可）** と
> **C2PA マニフェスト**（`python3 tools/export.py schema.org|c2pa|import <file>`）。
> schema.org は書き出し→読み戻しで id・title・authors・content_hash が復元でき
> （`import` サブコマンド）、C2PA は content_hash・署名・来歴・rendition を
> マニフェスト JSON に写す。MusicXML・OpenTimelineIO・EPUB・PDF への書き出しは
> **未実装**で、表は「目指す方向」。実装したものから「実装済み」と明記する。
> 「標準 (standard)」を名乗るのは外部採用が確認されてからとし、現状は
> 「公開された個人仕様 (public personal spec)」として扱う。

| kind | 変換先（実装済み / 方向性） |
|---|---|
| book | schema.org（実装済み） / EPUB / PDF（方向性） |
| movie | schema.org・C2PA（実装済み） / OpenTimelineIO / ffmpeg / Remotion |
| music | schema.org・C2PA（実装済み） / MusicXML / DAW / Suno・MUREKA プロンプト |
| voice / radio | schema.org・C2PA（実装済み） / KOE / teai TTS |
| product | schema.org（実装済み） / 社内カタログ |

### bim と bim.house

`bim/v1.json` は [bim.house/spec/v1.json](https://bim.house/spec/v1.json) の完全
スキーマ (project / applicant / designer / supervisor / contractor / road_access /
ground_investigation / permit / rooms / mep / elements / audit / attachments /
`$defs`) を、openformats の envelope と統合したもの。共通フィールド
(`content_hash`・`hash_chain`・`renditions`・`consent`・`rights`・`provenance` 等)
は `core/envelope/v1.json` を `$ref` で継承し、`kind: "bim"` を付けて作品として
扱えるようにする。bim.house ネイティブの物件 JSON は `kind`/`id` を持たないため、
openformats 作品にするにはこの 2 つを補う（[examples/sample.bim.json](examples/sample.bim.json) 参照）。

JSON は「創作の最小単位」を表し、実体は rendition に逃がす。これにより、
どのエディタ・DAW・レンダラとも相互変換できる。
