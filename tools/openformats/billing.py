"""課金導線 — プラン定義・使用量計量・上限判定。外部依存ゼロ。

作品数 (JSON 件数) とバイナリ容量 (ストアのユニークバイト) を分けて計量し、
プラン上限に対する状態 (ok / warning / over) を返す。課金そのもの (Stripe) は
ここでは呼ばない。判定結果を課金導線 (アップグレード案内・超過請求) に渡す。

方針:
    - 作品数と容量は別枠。1 本の長編動画と 1 曲で原価が桁違いだから。
    - 上限に近づいたら warning、超えたら over。over でも即停止せず、まず案内。
    - 課金の確定 (請求・サブスク作成) は別承認。ここは判定と下書きまで。

使い方 (ライブラリ):
    from openformats import billing
    u = billing.measure(works_dir="works", store_root=".ofstore")
    s = billing.evaluate(u, plan="personal")
    # -> {"plan":..., "status":"ok|warning|over", "works":{...}, "storage":{...}, ...}

使い方 (CLI):
    python3 tools/of.py billing --plan personal --works-dir works --store .ofstore
    python3 tools/of.py billing --plan personal --works-dir works --json
"""
from __future__ import annotations

import pathlib

from . import cost

# 上限の何割で warning を出すか
WARN_RATIO = 0.9


def count_works(works_dir: str) -> int:
    """作品 JSON の件数 (ディレクトリ直下と配下の *.json)。"""
    p = pathlib.Path(works_dir)
    if not p.exists():
        return 0
    return sum(1 for _ in p.rglob("*.json"))


def store_bytes(store_root: str) -> int:
    from . import store as storemod
    return storemod.Store(store_root).usage()["unique_bytes"]


def measure(*, works_dir: str = "works", store_root: str = ".ofstore") -> dict:
    """実測: 作品数と容量。"""
    b = store_bytes(store_root)
    return {
        "works": count_works(works_dir),
        "storage_bytes": b,
        "storage_gb": round(b / (1024 ** 3), 6),
    }


def _ratio_status(used: float, limit: float, warn: float = WARN_RATIO) -> str:
    if limit <= 0:
        return "over" if used > 0 else "ok"
    r = used / limit
    if r > 1.0:
        return "over"
    if r >= warn:
        return "warning"
    return "ok"


def evaluate(usage: dict, *, plan: str) -> dict:
    """使用量をプラン上限と照合し、状態と次の一手を返す。"""
    if plan not in cost.PLANS:
        raise KeyError(f"未知のプラン: {plan} (既知: {', '.join(cost.PLANS)})")
    spec = cost.PLANS[plan]
    works = usage.get("works", 0)
    gb = usage.get("storage_gb", 0.0)

    works_status = _ratio_status(works, spec["works"])
    storage_status = _ratio_status(gb, spec["storage_gb"])
    statuses = [works_status, storage_status]
    overall = "over" if "over" in statuses else ("warning" if "warning" in statuses else "ok")

    next_plan = None
    order = ["free", "personal", "studio"]
    if overall == "over" and plan in order:
        i = order.index(plan)
        if i + 1 < len(order):
            next_plan = order[i + 1]

    actions = []
    if works_status == "over":
        actions.append(f"作品数 {works} が上限 {spec['works']} を超過。プラン変更を案内する。")
    elif works_status == "warning":
        actions.append(f"作品数 {works} が上限 {spec['works']} の 90% 超。事前案内を出す。")
    if storage_status == "over":
        actions.append(f"容量 {gb:.2f}GB が上限 {spec['storage_gb']}GB を超過。超過請求 (¥100/10GB) またはプラン変更。")
    elif storage_status == "warning":
        actions.append(f"容量 {gb:.2f}GB が上限 {spec['storage_gb']}GB の 90% 超。事前案内を出す。")

    return {
        "plan": plan,
        "status": overall,
        "works": {"used": works, "limit": spec["works"], "status": works_status},
        "storage": {"used_gb": round(gb, 4), "limit_gb": spec["storage_gb"],
                    "status": storage_status},
        "next_plan": next_plan,
        "actions": actions,
        "note": "課金の確定・請求は別承認。ここは判定と案内の下書きまで。",
    }


def overage_charge_jpy(*, storage_gb: float, plan: str,
                       per_10gb_jpy: int = 100) -> int:
    """容量超過分の月額 (10GB 刻み)。"""
    spec = cost.PLANS[plan]
    over = storage_gb - spec["storage_gb"]
    if over <= 0:
        return 0
    import math
    return math.ceil(over / 10.0) * per_10gb_jpy
