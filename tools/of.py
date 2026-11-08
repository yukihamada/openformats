#!/usr/bin/env python3
"""openformats CLI — ハッシュ・署名・検証・バージョン管理・モデル移行。

使い方:
    # content_hash を計算して表示
    python3 tools/of.py hash work.json

    # content_hash を計算し直して書き込む
    python3 tools/of.py hash work.json --write

    # 鍵生成 (秘密鍵は表示しない。--key-out でファイル保存)
    python3 tools/of.py keygen --key-out ~/.openformats/secret.b64

    # content_hash に署名 (既存署名は同一公開鍵なら置換)
    python3 tools/of.py sign work.json --key ~/.openformats/secret.b64 \
        --signer yuki --write

    # 署名とチェーンを検証
    python3 tools/of.py verify work.json

    # 改訂を積む (現 content_hash を hash_chain に、履歴に 1 行)
    python3 tools/of.py revise work.json --action edit --by yuki --note "歌詞修正" --write

    # モデル移行: 既存 rendition の系譜を引き継いで新 rendition を足す
    #   (媒体生成は render.py。ここは JSON 側の来歴更新のみ)
    python3 tools/of.py migrate work.json --from <prev_sha256> --model koe-v3 --write
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from openformats import core  # noqa: E402


def _load(p):
    return core.load(p)


def cmd_hash(args):
    data = _load(args.work)
    h = core.content_hash(data)
    print(h)
    if args.write:
        data["content_hash"] = h
        core.dump(data, args.work)
        print(f"書き込み: {args.work}", file=sys.stderr)
    return 0


def cmd_keygen(args):
    secret = core.new_secret()
    pub = core.public_from_secret_b64(core.secret_to_b64(secret))
    if args.key_out:
        p = pathlib.Path(args.key_out).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(core.secret_to_b64(secret) + "\n")
        p.chmod(0o600)
        print(f"秘密鍵を保存: {p} (パーミッション 600)")
    else:
        print("秘密鍵 (base64):", core.secret_to_b64(secret))
    print("公開鍵 (base64):", pub)
    return 0


def cmd_sign(args):
    data = _load(args.work)
    key = pathlib.Path(args.key).expanduser().read_text().strip()
    from datetime import datetime, timezone
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    core.sign_document(data, key, signer=args.signer, signed_at=at)
    print(json.dumps({"content_hash": data["content_hash"],
                      "signatures": len(data["signatures"])}, ensure_ascii=False))
    if args.write:
        core.dump(data, args.work)
        print(f"書き込み: {args.work}", file=sys.stderr)
    return 0


def _verify_renditions(data, work_path):
    """renditions[].path の実体が存在し、sha256 が一致するか確認する。

    path は作品 JSON からの相対パスとして解決する。実体が無い/不一致でも
    例外にせず結果に含める (欠落を検知できることが目的)。
    """
    import os
    base = os.path.dirname(os.path.abspath(work_path))
    results = []
    for r in data.get("renditions", []):
        rel = r.get("path")
        want = r.get("sha256")
        entry = {"path": rel, "expected": want, "ok": False}
        if not rel:
            entry["error"] = "path 未設定"
            results.append(entry)
            continue
        full = rel if os.path.isabs(rel) else os.path.join(base, rel)
        if not os.path.exists(full):
            entry["error"] = "実体が見つからない"
            results.append(entry)
            continue
        got = core.rendition_hash(full)
        entry["actual"] = got
        entry["ok"] = (got == want)
        if not entry["ok"]:
            entry["error"] = "sha256 不一致"
        results.append(entry)
    return results


def cmd_verify(args):
    data = _load(args.work)
    h = core.content_hash(data)
    stored = data.get("content_hash")
    sigs = core.verify_signatures(data)
    chain = core.verify_chain(data)
    rends = _verify_renditions(data, args.work)
    out = {
        "work": data.get("id"),
        "content_hash_computed": h,
        "content_hash_stored": stored,
        "content_hash_match": stored == h if stored else None,
        "signatures": sigs,
        "chain": chain,
        "renditions": rends,
    }
    ok = (stored == h) if stored else True
    ok = ok and all(s["valid"] for s in sigs) and chain["ok"]
    ok = ok and all(r["ok"] for r in rends)
    out["ok"] = ok
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def cmd_revise(args):
    data = _load(args.work)
    core.append_revision(data, args.action, by=args.by, note=args.note)
    data["content_hash"] = core.content_hash(data)
    print(json.dumps({"content_hash": data["content_hash"],
                      "chain_length": len(data["hash_chain"])},
                     ensure_ascii=False))
    if args.write:
        core.dump(data, args.work)
        print(f"書き込み: {args.work}", file=sys.stderr)
    return 0


def cmd_migrate(args):
    """モデル移行の計画を出す。データは書き換えない。

    実体の無い rendition を JSON に足すとスキーマ不正になるため、ここでは
    派生元を特定し、実行すべき render.py コマンドを提示するだけにする。
    実際の差し替えは render.py --migrate-from <sha256> が media を生成し
    sha256 を埋めて renditions に追加する。
    """
    data = _load(args.work)
    rends = data.get("renditions", [])
    src = [r for r in rends if r.get("sha256") == args.from_]
    if not src and args.from_ != "latest":
        raise SystemExit(f"派生元 rendition が見つからない: {args.from_}")
    target = src[-1] if src else (rends[-1] if rends else None)
    if target is None:
        raise SystemExit("rendition が 1 つも無い。先に render.py で媒体化する")
    cmd = (f"python3 tools/render.py {args.work} --kind {target.get('kind')} "
           f"--format {target.get('format')} --model {args.model} "
           f"--migrate-from {target['sha256']} --write")
    print(json.dumps({
        "migrated_from": target["sha256"],
        "from_model": target.get("model"),
        "to_model": args.model,
        "note": "計画のみ。実体生成は下記コマンドで行い、sha256 を埋めてから追加する。",
        "run": cmd,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_revise(args):
    data = _load(args.work)
    core.append_revision(data, args.action, by=args.by, note=args.note)
    if args.write:
        core.dump(data, args.work)
        print(f"書き込み: {args.work}", file=sys.stderr)
    else:
        print(json.dumps(data.get("hash_chain", [])[-1:], ensure_ascii=False, indent=2))
    return 0


def cmd_record(args):
    """現在の本体と直前版の差分を revisions に記録する (差分保存)。"""
    data = _load(args.work)
    core.record_revision(data, action=args.action, by=args.by, note=args.note)
    if args.write:
        core.dump(data, args.work)
        print(f"記録: {args.work} (revisions={len(data.get('revisions', []))})", file=sys.stderr)
    else:
        print(json.dumps(core.revision_log(data)[-1:], ensure_ascii=False, indent=2))
    return 0


def cmd_log(args):
    """revisions の履歴を表示する。"""
    data = _load(args.work)
    print(json.dumps(core.revision_log(data), ensure_ascii=False, indent=2))
    return 0


def cmd_checkout(args):
    """指定リビジョン時点の本体を復元して出力する。"""
    data = _load(args.work)
    body = core.checkout(data, args.index)
    out = args.out or f"{pathlib.Path(args.work).stem}.rev{args.index}.json"
    core.dump(body, out)
    print(json.dumps({"restored": out, "index": args.index,
                      "content_hash": core.content_hash(body)}, ensure_ascii=False, indent=2))
    return 0


def cmd_store(args):
    """バイナリを content-addressed ストアにチャンク保存し、使用量を出す。"""
    from openformats import store as storemod
    st = storemod.Store(args.store or ".ofstore")
    if args.file:
        m = st.put_file_chunked(args.file)
        print(json.dumps(m, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(st.usage(), ensure_ascii=False, indent=2))
    return 0


def cmd_voice_attach(args):
    """参照音声を voice.json の clone ブロックに取り込む (qwen-tts 用)。"""
    from openformats import voiceclone
    data = _load(args.work)
    voiceclone.attach_reference(data, args.audio, text=args.text, lang=args.lang,
                                engine=args.engine)
    problems = voiceclone.validate_clone(data)
    if problems:
        print(json.dumps({"problems": problems}, ensure_ascii=False, indent=2))
        return 1
    if args.write:
        core.dump(data, args.work)
        print(f"記録: {args.work}", file=sys.stderr)
    else:
        print(json.dumps(data.get("clone"), ensure_ascii=False, indent=2))
    return 0


def cmd_voice_args(args):
    """qwen-tts に渡すクローン引数を出力する (自己完結性・同意を検査)。"""
    from openformats import voiceclone
    data = _load(args.work)
    problems = voiceclone.validate_clone(data)
    if problems:
        print(json.dumps({"problems": problems}, ensure_ascii=False, indent=2))
        return 1
    a = voiceclone.qwen_tts_args(data)
    if isinstance(a.get("ref_audio"), (bytes, bytearray)):
        a = dict(a)
        a["ref_audio"] = f"<{len(a['ref_audio'])} bytes>"
    print(json.dumps(a, ensure_ascii=False, indent=2))
    return 0


def cmd_cost(args):
    """プラン原価・粗利・損益分岐を計算する。"""
    from openformats import cost
    prices = {}
    if args.storage_price is not None:
        prices["storage_usd_per_gb_month"] = args.storage_price
    if args.egress_price is not None:
        prices["egress_usd_per_gb"] = args.egress_price
    if args.usd_jpy is not None:
        prices["usd_jpy"] = args.usd_jpy
    store_gb = args.storage_gb
    if store_gb is None and args.store:
        store_gb = cost.store_usage_gb(args.store)
    if args.plan:
        r = cost.plan_report(args.plan, egress_gb=args.egress_gb,
                             store_gb=store_gb, prices=prices or None)
    else:
        r = cost.plan_cost(storage_gb=store_gb or 0, egress_gb=args.egress_gb,
                           price_jpy=args.price_jpy, prices=prices or None)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


def cmd_billing(args):
    """使用量を計量し、プラン上限と照合する。"""
    from openformats import billing
    u = billing.measure(works_dir=args.works_dir, store_root=args.store)
    r = billing.evaluate(u, plan=args.plan)
    r["measured"] = u
    if args.overage:
        r["overage_jpy"] = billing.overage_charge_jpy(
            storage_gb=u["storage_gb"], plan=args.plan)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["status"] != "over" else 2


def cmd_consent(args):
    """声クローンの同意フロー (status/request/grant/deny/revoke)。"""
    from openformats import consent
    data = _load(args.work)
    if args.action == "status":
        print(json.dumps({
            "status": consent.status(data),
            "can_synthesize": consent.can_synthesize(data),
            "events": data.get("clone", {}).get("consent", {}).get("events", []),
            "problems": consent.validate(data),
        }, ensure_ascii=False, indent=2))
        return 0
    if args.action == "request":
        consent.request(data, subject=args.subject, doc=args.doc, by=args.by, note=args.note)
    elif args.action == "grant":
        consent.grant(data, by=args.by or "self", scope=args.scope, doc=args.doc, note=args.note)
    elif args.action == "deny":
        consent.deny(data, by=args.by, note=args.note)
    elif args.action == "revoke":
        consent.revoke(data, by=args.by or "self", note=args.note)
    problems = consent.validate(data)
    if problems:
        print(json.dumps({"problems": problems}, ensure_ascii=False, indent=2))
        return 1
    if args.write:
        core.dump(data, args.work)
        print(f"記録: {args.work} (status={consent.status(data)})", file=sys.stderr)
    else:
        print(json.dumps(data.get("clone", {}).get("consent"), ensure_ascii=False, indent=2))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(prog="of", description="openformats CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("hash"); p.add_argument("work"); p.add_argument("--write", action="store_true"); p.set_defaults(fn=cmd_hash)
    p = sub.add_parser("keygen"); p.add_argument("--key-out"); p.set_defaults(fn=cmd_keygen)
    p = sub.add_parser("sign"); p.add_argument("work"); p.add_argument("--key", required=True); p.add_argument("--signer"); p.add_argument("--write", action="store_true"); p.set_defaults(fn=cmd_sign)
    p = sub.add_parser("verify"); p.add_argument("work"); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("revise"); p.add_argument("work"); p.add_argument("--action", default="edit"); p.add_argument("--by"); p.add_argument("--note"); p.add_argument("--write", action="store_true"); p.set_defaults(fn=cmd_revise)
    p = sub.add_parser("migrate"); p.add_argument("work"); p.add_argument("--from", dest="from_", required=True); p.add_argument("--model", required=True); p.add_argument("--model-version"); p.set_defaults(fn=cmd_migrate)
    p = sub.add_parser("record"); p.add_argument("work"); p.add_argument("--action", default="edit"); p.add_argument("--by"); p.add_argument("--note"); p.add_argument("--write", action="store_true"); p.set_defaults(fn=cmd_record)
    p = sub.add_parser("log"); p.add_argument("work"); p.set_defaults(fn=cmd_log)
    p = sub.add_parser("checkout"); p.add_argument("work"); p.add_argument("index", type=int); p.add_argument("--out"); p.set_defaults(fn=cmd_checkout)
    p = sub.add_parser("store"); p.add_argument("file", nargs="?"); p.add_argument("--store"); p.set_defaults(fn=cmd_store)
    p = sub.add_parser("voice-attach"); p.add_argument("work"); p.add_argument("audio"); p.add_argument("--text", required=True); p.add_argument("--lang"); p.add_argument("--engine", default="qwen-tts"); p.add_argument("--write", action="store_true"); p.set_defaults(fn=cmd_voice_attach)
    p = sub.add_parser("voice-args"); p.add_argument("work"); p.set_defaults(fn=cmd_voice_args)
    p = sub.add_parser("cost"); p.add_argument("--plan"); p.add_argument("--storage-gb", type=float); p.add_argument("--egress-gb", type=float, default=0.0); p.add_argument("--price-jpy", type=float, default=0.0); p.add_argument("--store"); p.add_argument("--storage-price", type=float); p.add_argument("--egress-price", type=float); p.add_argument("--usd-jpy", type=float); p.set_defaults(fn=cmd_cost)
    p = sub.add_parser("billing"); p.add_argument("--plan", required=True); p.add_argument("--works-dir", default="works"); p.add_argument("--store", default=".ofstore"); p.add_argument("--overage", action="store_true"); p.set_defaults(fn=cmd_billing)
    p = sub.add_parser("consent"); p.add_argument("action", choices=["status", "request", "grant", "deny", "revoke"]); p.add_argument("work"); p.add_argument("--subject"); p.add_argument("--doc"); p.add_argument("--by"); p.add_argument("--note"); p.add_argument("--scope", action="append"); p.add_argument("--write", action="store_true"); p.set_defaults(fn=cmd_consent)

    args = ap.parse_args(argv[1:])
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
