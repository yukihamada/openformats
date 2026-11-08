"""原価実測 — ホスト型プランの原価と粗利を、実測値から計算する。外部依存ゼロ。

PRICING.md の「推定」を「実測」に置き換えるための道具。ストレージ・配信・課金手数料を
実測バイト数と単価から積み上げ、プランごとの粗利と損益分岐を出す。

単価は既定値 (2026 時点の概算) を持つが、必ず引数や設定で上書きして実測する。
「推定のまま確定価格として案内しない」ため、出力に source="estimate" を明示する。

使い方 (ライブラリ):
    from openformats import cost
    r = cost.plan_cost(storage_gb=20, egress_gb=20, price_jpy=500)
    # -> {"revenue_jpy":..., "cost_jpy":..., "margin_jpy":..., "margin_pct":..., ...}

使い方 (CLI):
    python3 tools/of.py cost --storage-gb 20 --egress-gb 20 --price-jpy 500
    python3 tools/of.py cost --store .ofstore --price-jpy 500   # 実ストアの実測容量で計算
"""
from __future__ import annotations

# 既定単価 (USD)。2026 時点の概算。実測時は必ず上書きする。
DEFAULT_PRICES = {
    "storage_usd_per_gb_month": 0.015,   # オブジェクトストレージ
    "egress_usd_per_gb": 0.05,           # 配信 (CDN 込みの目安)
    "stripe_pct": 0.036,                 # Stripe 日本
    "stripe_fixed_jpy": 0,               # 固定手数料 (JPY 決済は概ね 0)
    "usd_jpy": 150.0,                    # 為替 (実測時に更新)
}

# プラン定義 (PRICING.md と一致させる)
PLANS = {
    "free":     {"price_jpy": 0,    "works": 100,   "storage_gb": 1},
    "personal": {"price_jpy": 500,  "works": 10_000, "storage_gb": 20},
    "studio":   {"price_jpy": 3000, "works": 100_000, "storage_gb": 200},
}


def _usd_to_jpy(usd: float, usd_jpy: float) -> float:
    return usd * usd_jpy


def plan_cost(*, storage_gb: float, egress_gb: float, price_jpy: float,
              prices: dict | None = None, source: str = "estimate") -> dict:
    """1 契約あたりの月次原価・粗利を計算する。

    storage_gb: 保存容量 (GB, ユニーク)
    egress_gb:  月間配信量 (GB)
    price_jpy:  月額 (円)
    """
    p = dict(DEFAULT_PRICES)
    if prices:
        p.update(prices)
    storage_usd = storage_gb * p["storage_usd_per_gb_month"]
    egress_usd = egress_gb * p["egress_usd_per_gb"]
    infra_usd = storage_usd + egress_usd
    infra_jpy = _usd_to_jpy(infra_usd, p["usd_jpy"])
    stripe_jpy = price_jpy * p["stripe_pct"] + p["stripe_fixed_jpy"]
    cost_jpy = infra_jpy + stripe_jpy
    margin_jpy = price_jpy - cost_jpy
    margin_pct = (margin_jpy / price_jpy * 100.0) if price_jpy else 0.0
    return {
        "source": source,
        "storage_gb": storage_gb,
        "egress_gb": egress_gb,
        "price_jpy": price_jpy,
        "cost_breakdown_jpy": {
            "storage": round(_usd_to_jpy(storage_usd, p["usd_jpy"]), 1),
            "egress": round(_usd_to_jpy(egress_usd, p["usd_jpy"]), 1),
            "stripe": round(stripe_jpy, 1),
        },
        "cost_jpy": round(cost_jpy, 1),
        "margin_jpy": round(margin_jpy, 1),
        "margin_pct": round(margin_pct, 1),
        "prices": p,
    }


def breakeven_egress_gb(*, storage_gb: float, price_jpy: float,
                        prices: dict | None = None) -> float:
    """粗利 0 になる配信量 (GB/月) を返す。上限の安全確認に使う。"""
    p = dict(DEFAULT_PRICES)
    if prices:
        p.update(prices)
    stripe_jpy = price_jpy * p["stripe_pct"] + p["stripe_fixed_jpy"]
    budget_usd = (price_jpy - stripe_jpy) / p["usd_jpy"]
    budget_usd -= storage_gb * p["storage_usd_per_gb_month"]
    if budget_usd <= 0:
        return 0.0
    return round(budget_usd / p["egress_usd_per_gb"], 1)


def store_usage_gb(store_root: str) -> float:
    """ローカルストアの実測ユニーク容量 (GB)。"""
    from . import store as storemod
    u = storemod.Store(store_root).usage()
    return u["unique_bytes"] / (1024 ** 3)


def plan_report(plan: str, *, egress_gb: float, store_gb: float | None = None,
                prices: dict | None = None) -> dict:
    """既知プランの原価レポート。store_gb 未指定ならプラン上限で最悪ケースを試算。"""
    if plan not in PLANS:
        raise KeyError(f"未知のプラン: {plan} (既知: {', '.join(PLANS)})")
    spec = PLANS[plan]
    gb = store_gb if store_gb is not None else spec["storage_gb"]
    r = plan_cost(storage_gb=gb, egress_gb=egress_gb, price_jpy=spec["price_jpy"],
                  prices=prices)
    r["plan"] = plan
    r["limits"] = {"works": spec["works"], "storage_gb": spec["storage_gb"]}
    r["breakeven_egress_gb"] = breakeven_egress_gb(
        storage_gb=gb, price_jpy=spec["price_jpy"], prices=prices)
    return r
