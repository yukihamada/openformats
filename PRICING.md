# PRICING — ホスト型プランと、フォークして自前で運用する自由

> openformats の仕様そのものは **無料・オープン**（このリポジトリのまま）。
> ここで書くのは、面倒な保存・配信・課金を代わりに引き受ける **ホスト型プラン** の設計。
> 誰でもフォークして、自分の値段で、自分のユーザーに提供できる。

---

## 1. なぜ課金するのか

openformats のファイルは、あなたの `git` の中に残る。だから「預ける」必要はない。
ホスト型が売るのは **保存・配信・課金・運用の手間をなくすこと** であって、作品を人質に取ることではない。

- **ロックインしない** — いつでも `git clone` で全作品を JSON のまま持ち出せる。
- **消えない** — バイナリは content-addressed。同じ音源を何度レンダリングしても、保存は差分だけ。
- **安い** — 差分保存と重複排除で、原価の大半（ストレージ）を構造的に下げている。

---

## 2. プラン（案）

| プラン | 月額 | 作品数 | 保存容量 | 想定ユーザー |
|---|---|---|---|---|
| Free | ¥0 | 100 | 1 GB | 試す人・個人の小作品 |
| **Personal** | **¥500** | **1 万** | **20 GB** | 継続的に作る個人 |
| Studio | ¥3,000 | 10 万 | 200 GB | 少人数チーム・制作会社 |
| Self-host | ¥0（自前） | 無制限 | 自分のディスク | フォークして自前運用 |

- **「1 万個」の定義**：作品 JSON の件数（`.json` の数）。バイナリは別枠で容量課金。
  作品数と容量を分けるのは、1 本の長編動画と 1 曲で原価が桁違いだから。
- **超過**：容量超過は ¥100 / 10 GB（月）。作品数超過は次のプランへ。
- **支払い**：Stripe サブスクリプション。年払いは 2 か月分無料。

> 価格は **提案段階**。原価（下記）と実測利用で確定する。確定前に「この値段で確定」とは言わない。

---

## 3. 原価（`tools/of.py cost` で実測・再計算できる）

原価は推測で書かず、ツールで計算する。単価は既定値（2026 概算）を持つが、必ず実測で上書きする。

```bash
# プランの原価・粗利・損益分岐（容量・配信を指定）
python3 tools/of.py cost --plan personal --egress-gb 20
# 実ストアの実測容量で計算
python3 tools/of.py cost --store .ofstore --price-jpy 500
# 単価を実測値に差し替え
python3 tools/of.py cost --plan personal --egress-gb 20 \
    --storage-price 0.015 --egress-price 0.05 --usd-jpy 150
```

**実測値（既定単価・¥150/$ で計算）:**

| プラン | 容量 / 配信 | 原価 | 粗利 | 粗利率 | 損益分岐配信量 |
|---|---|---|---|---|---|
| Personal ¥500 | 20GB / 20GB | ¥213 | ¥287 | 57.4% | 58.3 GB |
| Personal ¥500 | 20GB / 58GB（分岐点） | ¥498 | ¥2 | 0.4% | — |
| Studio ¥3,000 | 200GB / 200GB | ¥2,058 | ¥942 | 31.4% | 325.6 GB |

- 原価の内訳: ストレージ + 配信（egress）+ Stripe 手数料（3.6%）。
- **配信量が損益分岐（Personal で約 58GB/月）を超えると赤字**。ここが唯一の危険域。
- 全員が容量フルでも、配信が常識的な範囲なら黒字。配信だけを監視する。

> 出力の `source` が `estimate` の間は「推定」。実測単価に置き換えたときだけ確定値として扱う。
> 為替・単価・配信量は変わる。契約前に必ず実測で再計算する。

---

## 4. 差分保存が原価を下げる仕組み

同じ作品を新しいモデルで作り直しても、**変わったチャンクだけ** が保存される。

- 実測（テストより）: 20 万バイトのうち 3 バイト変更 → 新規保存は約 8.7%（17,476 バイト）。
- つまり「声だけ差し替え」「1 行だけ推敲」を繰り返しても、ストレージはほぼ増えない。
- 作品本体の `content_hash` は変わらないので、派生（rendition）を足すほど価値が積み上がる。

これは原価だけでなく **ユーザー体験**（再レンダリングが速い・安い）にも効く。

---

## 5. フォークして自前で運用する

ホスト型を使わなくても、同じ仕組みを自分で回せる。

```bash
git clone https://github.com/yukihamada/openformats
cd openformats
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt   # jsonschema のみ
python3 tools/of.py verify examples/sample.book.json
```

- **保存**：`.ofstore/` はローカルの content-addressed ストア。`python3 tools/of.py store` で使用量が見える。
- **配信**：静的ホスティング（Cloudflare Pages / GitHub Pages / S3）にそのまま置ける。
- **課金**：自前で Stripe を繋ぐ。仕様はオープンなので、値段もルールも自分で決められる。
- **データの持ち出し**：全作品は JSON。`git clone` 一発で移行できる。ロックインは構造的に起きない。

> フォーク運用者に求めるのは 1 つだけ：**声・肖像・土地の同意と権利を、構造として記録し続けること**（`voice/v1.json` の `clone` と `speaker.consent`）。これは仕様の安全原則で、値段より優先する。

---

## 6. 課金導線（`tools/of.py billing`）

使用量を計量し、プラン上限と照合して状態（ok / warning / over）と次の一手を返す。
課金の確定（請求・サブスク作成）はここでは行わない。判定と案内の下書きまで。

```bash
python3 tools/of.py billing --plan personal --works-dir works --store .ofstore --overage
```

- **作品数**（JSON 件数）と**容量**（ストアのユニークバイト）を別枠で判定。
- 上限の 90% で `warning`、超過で `over`。`over` は終了コード 2。
- `next_plan`（free→personal→studio）と超過請求（¥100/10GB）を提示。
- 課金の確定は別承認。ここは「いつ・誰に・いくら案内するか」を決める材料。

## 7. 声クローンの同意フロー（`tools/of.py consent`）

声の再現は、話者の同意が前提。口約束でなく状態機械として記録する。

```bash
python3 tools/of.py consent request work.voice.json --subject 濱田優貴 --doc internal:consent-2026 --write
python3 tools/of.py consent grant   work.voice.json --by self --scope tts --scope render --write
python3 tools/of.py consent status  work.voice.json
python3 tools/of.py consent revoke  work.voice.json --by self --note 配布停止 --write
```

- 状態: `requested → granted → revoked`（`denied` も）。各遷移は `events` に追記のみ。
- **撤回（revoked）後は合成・配布を禁止**（`can_synthesize=false`）。撤回後に再 grant は不可。
- 用途（scope: tts / render / distribute）ごとに許諾範囲を検査。
- 同意なきクローンは `validate` が検出し、`voice-args` が引数生成を拒否する。

> 法務確認（同意書の文言・撤回の実効性・未成年の扱い）は別途必要。仕組みは用意済み。

## 8. 未確定・これから決めること

- [ ] 実測単価（ストレージ・配信の実契約額）での再計算
- [ ] 無料プランの悪用対策（容量・帯域の濫用）
- [ ] 声クローン同意書の法務確認（文言・撤回の実効性・未成年）
- [ ] 年払い・チーム割引の具体額
- [ ] Stripe 実接続（サブスク作成・Webhook・請求）の本番実装

**確定前の数字を、確定した価格として案内しない。**
