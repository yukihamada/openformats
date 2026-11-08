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


def cmd_verify(args):
    data = _load(args.work)
    h = core.content_hash(data)
    stored = data.get("content_hash")
    sigs = core.verify_signatures(data)
    chain = core.verify_chain(data)
    out = {
        "work": data.get("id"),
        "content_hash_computed": h,
        "content_hash_stored": stored,
        "content_hash_match": stored == h if stored else None,
        "signatures": sigs,
        "chain": chain,
    }
    ok = (stored == h) if stored else True
    ok = ok and all(s["valid"] for s in sigs) and chain["ok"]
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
    data = _load(args.work)
    rends = data.get("renditions", [])
    src = [r for r in rends if r.get("sha256") == args.from_]
    if not src and args.from_ != "latest":
        raise SystemExit(f"派生元 rendition が見つからない: {args.from_}")
    target = src[-1] if src else (rends[-1] if rends else None)
    if target is None:
        raise SystemExit("rendition が 1 つも無い。先に render.py で媒体化する")
    new = dict(target)
    new["model"] = args.model
    if args.model_version:
        new["model_version"] = args.model_version
    new["source_rendition"] = target["sha256"]
    new.pop("sha256", None)  # 実体ハッシュは render.py が埋める
    new.pop("path", None)
    new.pop("bytes", None)
    from datetime import datetime, timezone
    new["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data.setdefault("renditions", []).append(new)
    core.append_revision(data, "migrate",
                         note=f"{target.get('kind')} を {args.model} へ移行予定")
    print(json.dumps({"migrated_from": target["sha256"], "model": args.model,
                      "note": "媒体実体は render.py で生成し sha256 を埋める"},
                     ensure_ascii=False, indent=2))
    if args.write:
        core.dump(data, args.work)
        print(f"書き込み: {args.work}", file=sys.stderr)
    return 0


def main(argv):
    ap = argparse.ArgumentParser(prog="of", description="openformats CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("hash"); p.add_argument("work"); p.add_argument("--write", action="store_true"); p.set_defaults(fn=cmd_hash)
    p = sub.add_parser("keygen"); p.add_argument("--key-out"); p.set_defaults(fn=cmd_keygen)
    p = sub.add_parser("sign"); p.add_argument("work"); p.add_argument("--key", required=True); p.add_argument("--signer"); p.add_argument("--write", action="store_true"); p.set_defaults(fn=cmd_sign)
    p = sub.add_parser("verify"); p.add_argument("work"); p.set_defaults(fn=cmd_verify)
    p = sub.add_parser("revise"); p.add_argument("work"); p.add_argument("--action", default="edit"); p.add_argument("--by"); p.add_argument("--note"); p.add_argument("--write", action="store_true"); p.set_defaults(fn=cmd_revise)
    p = sub.add_parser("migrate"); p.add_argument("work"); p.add_argument("--from", dest="from_", required=True); p.add_argument("--model", required=True); p.add_argument("--model-version"); p.add_argument("--write", action="store_true"); p.set_defaults(fn=cmd_migrate)

    args = ap.parse_args(argv[1:])
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
