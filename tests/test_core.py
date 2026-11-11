#!/usr/bin/env python3
"""openformats コアの回帰テスト。外部依存なしで pytest でも直接実行でも動く。

    python3 tests/test_core.py
    pytest tests/
"""
import copy
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from openformats import core, ed25519  # noqa: E402
from openformats.canonical import canonicalize, _num_to_es  # noqa: E402


def _base():
    return {
        "spec_version": "1.0.0", "kind": "music", "id": "t",
        "title": "t", "lyrics": [{"lines": ["a"]}],
        "provenance": {"human_involvement": "human", "history": []},
    }


def test_jcs_numbers():
    cases = [(0.0, "0"), (-0.0, "0"), (1.0, "1"), (1.5, "1.5"), (0.1, "0.1"),
             (1e21, "1e+21"), (1e-7, "1e-7"), (1e20, "100000000000000000000"),
             (0.000001, "0.000001")]
    for v, e in cases:
        assert _num_to_es(v) == e, (v, _num_to_es(v), e)


def test_jcs_key_order():
    assert canonicalize({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_ed25519_rfc8032():
    sk = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    pk = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    sig = ed25519.sign(sk, b"")
    assert ed25519.publickey(sk) == pk
    assert ed25519.verify(pk, b"", sig)
    assert not ed25519.verify(pk, b"x", sig)


def test_hash_stable():
    a = _base()
    assert core.content_hash(a) == core.content_hash(copy.deepcopy(a))


def test_history_excluded_from_hash():
    a = _base()
    h0 = core.content_hash(a)
    a["provenance"]["history"].append({"at": "2026-01-01T00:00:00Z", "action": "edit"})
    assert core.content_hash(a) == h0


def test_rendition_excluded_from_hash():
    a = _base()
    h0 = core.content_hash(a)
    a["renditions"] = [{"kind": "audio", "format": "wav", "sha256": "0" * 64}]
    assert core.content_hash(a) == h0


def test_content_edit_changes_hash():
    a = _base()
    h0 = core.content_hash(a)
    a["lyrics"][0]["lines"][0] = "b"
    assert core.content_hash(a) != h0


def test_sign_verify_roundtrip():
    a = _base()
    secret = core.secret_to_b64(core.new_secret())
    core.sign_document(a, secret, signer="me", signed_at="2026-01-01T00:00:00Z")
    res = core.verify_signatures(a)
    assert len(res) == 1 and res[0]["valid"]


def test_signature_invalid_after_edit():
    a = _base()
    secret = core.secret_to_b64(core.new_secret())
    core.sign_document(a, secret)
    a["lyrics"][0]["lines"][0] = "changed"
    assert not core.verify_signatures(a)[0]["valid"]


def test_chain_append():
    a = _base()
    a["content_hash"] = core.content_hash(a)
    core.append_revision(a, "edit", by="me")
    assert len(a["hash_chain"]) == 1
    assert core.verify_chain(a)["ok"]


def test_migration_preserves_identity():
    """声だけ差し替えても content_hash は不変 = 作品の同一性が保たれる。"""
    a = _base()
    h0 = core.content_hash(a)
    a.setdefault("renditions", []).append(
        {"kind": "audio", "format": "wav", "sha256": "a" * 64, "model": "v1"})
    a["renditions"].append(
        {"kind": "audio", "format": "wav", "sha256": "b" * 64, "model": "v2",
         "source_rendition": "a" * 64})
    core.append_revision(a, "migrate", note="v2")
    assert core.content_hash(a) == h0


def test_revisions_record_and_checkout():
    from openformats import core as c
    d = _base()
    c.record_revision(d, action="create", by="t", note="v0")
    h0 = c.content_hash(d)
    d["lyrics"][0]["lines"].append("b")
    c.record_revision(d, action="edit", by="t", note="v1")
    revs = d["revisions"]
    assert len(revs) == 2, revs
    assert revs[0]["patch"] == [], "base は patch 空"
    assert len(revs[1]["patch"]) >= 1, "2 版目は差分を持つ"
    # 復元
    r0 = c.checkout(d, 0)
    assert r0["lyrics"][0]["lines"] == ["a"], r0
    r1 = c.checkout(d, 1)
    assert r1["lyrics"][0]["lines"] == ["a", "b"], r1
    # revisions は content_hash 対象外なので、base 時点の hash と不変関係を保つ
    assert c.content_hash(d) != h0


def test_revisions_excluded_from_hash():
    from openformats import core as c
    d = _base()
    h = c.content_hash(d)
    d["revisions"] = [{"at": "2026-01-01T00:00:00Z", "action": "x",
                       "content_hash": h, "patch": [], "snapshot": {}}]
    assert c.content_hash(d) == h, "revisions を足しても content_hash 不変"


def test_jsonpatch_roundtrip():
    from openformats import jsonpatch
    cases = [
        ({"a": 1}, {"a": 2}),
        ({"arr": [1, 2, 3]}, {"arr": [1, 9, 3, 4]}),
        ({"arr": [1, 2, 3, 4]}, {"arr": [1, 2]}),
        ({"o": {"k": "v", "x": 1}}, {"o": {"k": "w"}}),
        ({"a": 1}, {"a": 1, "b": [1, {"c": 2}]}),
    ]
    for a, b in cases:
        p = jsonpatch.diff(a, b)
        assert jsonpatch.apply_patch(a, p) == b, (a, b, p)


def test_fastcdc_dedup():
    from openformats import chunking
    import random
    random.seed(7)
    base = bytes(random.getrandbits(8) for _ in range(150000))
    edited = base[:70000] + b"XYZ" + base[70003:]
    c1 = chunking.chunk_bytes(base)
    c2 = chunking.chunk_bytes(edited)
    assert b"".join(c1) == base
    assert b"".join(c2) == edited
    shared = set(c1) & set(c2)
    assert shared, "編集後も共通チャンクが残る (差分保存の根拠)"


def test_store_dedup_and_reassemble():
    from openformats import store
    import tempfile, os, random
    random.seed(3)
    base = bytes(random.getrandbits(8) for _ in range(120000))
    edited = base[:60000] + b"CHG" + base[60003:]
    d = tempfile.mkdtemp()
    p1 = os.path.join(d, "a.bin"); open(p1, "wb").write(base)
    p2 = os.path.join(d, "b.bin"); open(p2, "wb").write(edited)
    st = store.Store(os.path.join(d, "s"))
    m1 = st.put_file_chunked(p1)
    m2 = st.put_file_chunked(p2)
    assert m2["new_bytes"] < len(edited), "編集分だけ新規保存される"
    assert st.reassemble(m1["manifest_sha256"]) == base
    assert st.reassemble(m2["manifest_sha256"]) == edited


def test_voice_clone_selfcontained_and_consent():
    from openformats import voiceclone
    import tempfile, os, wave
    d = tempfile.mkdtemp()
    p = os.path.join(d, "ref.wav")
    with wave.open(p, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    voice = {"kind": "voice", "id": "v", "lang": "ja",
             "speaker": {"name": "t", "consent": "self"}}
    voiceclone.attach_reference(voice, p, text="こんにちは", lang="ja")
    assert voiceclone.validate_clone(voice) == []
    args = voiceclone.qwen_tts_args(voice)
    assert args["ref_text"] == "こんにちは"
    assert isinstance(args["ref_audio"], (bytes, bytearray))
    # 同意なしは拒否
    bad = {"kind": "voice", "id": "v", "speaker": {"name": "t", "consent": "synthetic"}}
    voiceclone.attach_reference(bad, p, text="x")
    assert voiceclone.validate_clone(bad), "同意なきクローンは問題として検出"


def test_cost_plan_margin():
    from openformats import cost
    r = cost.plan_cost(storage_gb=20, egress_gb=20, price_jpy=500)
    assert r["source"] == "estimate"
    assert r["price_jpy"] == 500
    assert 0 < r["cost_jpy"] < 500, r
    assert r["margin_jpy"] > 0, "¥500/20GB/20GB は赤字でない"
    assert abs(r["cost_jpy"] + r["margin_jpy"] - 500) < 0.5


def test_cost_breakeven_positive():
    from openformats import cost
    be = cost.breakeven_egress_gb(storage_gb=20, price_jpy=500)
    assert be > 0, "損益分岐の配信量が正"
    # 損益分岐を超えると赤字
    over = cost.plan_cost(storage_gb=20, egress_gb=be + 50, price_jpy=500)
    assert over["margin_jpy"] < 0


def test_billing_states():
    from openformats import billing
    ok = billing.evaluate({"works": 5, "storage_gb": 1}, plan="personal")
    assert ok["status"] == "ok", ok
    warn = billing.evaluate({"works": 9500, "storage_gb": 19}, plan="personal")
    assert warn["status"] == "warning", warn
    over = billing.evaluate({"works": 10001, "storage_gb": 1}, plan="personal")
    assert over["status"] == "over", over
    assert over["next_plan"] == "studio", over


def test_billing_overage():
    from openformats import billing
    assert billing.overage_charge_jpy(storage_gb=20, plan="personal") == 0
    assert billing.overage_charge_jpy(storage_gb=25, plan="personal") == 100
    assert billing.overage_charge_jpy(storage_gb=35, plan="personal") == 200


def test_consent_flow():
    from openformats import consent
    d = {"kind": "voice", "id": "v", "speaker": {"name": "t", "consent": "self"},
         "clone": {"engine": "qwen-tts", "method": "zero-shot"}}
    assert consent.status(d) is None
    assert not consent.can_synthesize(d)
    consent.request(d, subject="t", doc="internal:x")
    assert consent.status(d) == "requested"
    assert not consent.can_synthesize(d), "requested では合成不可"
    consent.grant(d, by="self", scope=["tts", "render"])
    assert consent.status(d) == "granted"
    assert consent.can_synthesize(d)
    assert consent.scope_allows(d, "render")
    assert not consent.scope_allows(d, "distribute")
    assert consent.validate(d) == []
    consent.revoke(d, by="self", note="停止")
    assert consent.status(d) == "revoked"
    assert not consent.can_synthesize(d), "撤回後は合成不可"
    assert consent.validate(d) == []


def test_consent_grant_after_revoke_fails():
    from openformats import consent
    d = {"kind": "voice", "id": "v", "clone": {"method": "zero-shot"}}
    consent.request(d, subject="t")
    consent.grant(d, by="self")
    consent.revoke(d, by="self")
    try:
        consent.grant(d, by="self")
        assert False, "撤回後に grant できてはいけない"
    except ValueError:
        pass


def test_revocation_blocks_synthesis():
    """#1: 撤回済みクローンは voiceclone でも合成できない (同意フローの実経路強制)。"""
    from openformats import consent, voiceclone
    d = {"kind": "voice", "id": "v", "lang": "ja",
         "speaker": {"name": "t", "consent": "self"},
         "clone": {"engine": "qwen-tts", "method": "zero-shot",
                   "reference": {"text": "hi", "audio_b64": "AAAA"}}}
    consent.request(d, subject="t")
    consent.grant(d, by="self", scope=["tts"])
    assert voiceclone.consent_ok(d)
    assert voiceclone.validate_clone(d) == []
    voiceclone.qwen_tts_args(d)  # 同意中は生成できる
    consent.revoke(d, by="self")
    assert not voiceclone.consent_ok(d), "撤回後は consent_ok が False"
    assert voiceclone.validate_clone(d), "撤回後は validate_clone が問題を出す"
    try:
        voiceclone.qwen_tts_args(d)
        assert False, "撤回後に合成引数を生成してはいけない"
    except PermissionError:
        pass


def test_revocation_blocks_synthesis_cli():
    """#1: CLI voice-args も撤回後は非0で拒否する。"""
    import json, subprocess, tempfile, os
    from openformats import consent, core
    d = {"kind": "voice", "id": "v", "lang": "ja",
         "speaker": {"name": "t", "consent": "self"},
         "clone": {"engine": "qwen-tts", "method": "zero-shot",
                   "reference": {"text": "hi", "audio_b64": "AAAA"}}}
    consent.request(d, subject="t")
    consent.grant(d, by="self", scope=["tts"])
    consent.revoke(d, by="self")
    p = os.path.join(tempfile.mkdtemp(), "v.json")
    core.dump(d, p)
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "of.py"),
                        "voice-args", p], capture_output=True, text=True)
    assert r.returncode != 0, f"撤回後は voice-args が失敗すべき: {r.stdout}"


def test_consent_excluded_from_hash_and_signature():
    """#5: 同意の grant/revoke は content_hash を変えず、署名を壊さない。"""
    from openformats import consent
    d = _base()
    d["clone"] = {"engine": "qwen-tts", "method": "zero-shot",
                  "reference": {"text": "hi"}}
    h0 = core.content_hash(d)
    consent.request(d, subject="t")
    consent.grant(d, by="self", scope=["tts"])
    h1 = core.content_hash(d)
    consent.revoke(d, by="self")
    h2 = core.content_hash(d)
    assert h0 == h1 == h2, "同意の状態変化で content_hash が変わってはいけない"
    # 署名も維持される
    sec = core.secret_to_b64(core.new_secret())
    d["content_hash"] = core.content_hash(d)
    core.sign_document(d, sec, signer="t")
    assert all(s["valid"] for s in core.verify_signatures(d))
    consent.request(d, subject="t")
    consent.grant(d, by="self", scope=["tts"])
    assert all(s["valid"] for s in core.verify_signatures(d)), \
        "同意付与で署名が無効になってはいけない"


def test_checkout_is_non_destructive():
    """#2: checkout の戻り値を編集しても履歴 snapshot を壊さない。"""
    d = _base()
    core.record_revision(d, action="create")
    d["title"] = "second"
    core.record_revision(d, action="edit")
    r0 = core.checkout(d, 0)
    r0["title"] = "HACKED"
    assert d["revisions"][0]["snapshot"]["title"] == "t", "履歴が破壊された"
    r1 = core.checkout(d, 1)
    r1["title"] = "HACKED2"
    assert core.checkout(d, 1)["title"] == "second", "復元結果が共有されている"


def test_diff_type_strict():
    """#3: 1 -> true を差分ゼロと誤判定しない (型を厳密に区別)。"""
    from openformats import jsonpatch
    p = jsonpatch.diff({"x": 1}, {"x": True})
    assert p, "1 -> true は差分あり"
    assert jsonpatch.apply_patch({"x": 1}, p) == {"x": True}
    # 1 -> 1.0 も型が違うので差分 (ただし content_hash は JCS で同一)
    p2 = jsonpatch.diff({"x": 1}, {"x": 1.0})
    assert p2, "int -> float は差分あり"
    # 同一型・同一値は差分なし
    assert jsonpatch.diff({"x": 1}, {"x": 1}) == []


def test_checkout_restores_bool_true():
    """#3: 1 -> true の改訂を checkout で正しく復元できる。"""
    d = _base()
    d["flag"] = 1
    core.record_revision(d, action="create")
    d["flag"] = True
    core.record_revision(d, action="edit")
    r = core.checkout(d, 1)
    assert r["flag"] is True, f"True を復元できていない: {r['flag']!r}"
    r0 = core.checkout(d, 0)
    assert r0["flag"] == 1 and not isinstance(r0["flag"], bool)


def test_verify_revisions_detects_drift():
    """#4: 本体だけ編集して record し忘れると verify_revisions が検知する。"""
    d = _base()
    core.record_revision(d, action="create")
    d["title"] = "changed without record"
    vr = core.verify_revisions(d)
    assert not vr["ok"], "record 漏れを検知できていない"
    # record すれば整合
    core.record_revision(d, action="edit")
    assert core.verify_revisions(d)["ok"]


def test_samples_are_self_consistent():
    """#4: リポジトリ内の全サンプル・作品が verify を通る。"""
    import glob, json
    for f in sorted(glob.glob(str(ROOT / "examples" / "*.json")) +
                    glob.glob(str(ROOT / "works" / "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        stored = d.get("content_hash")
        if stored:
            assert stored == core.content_hash(d), f"{f}: content_hash 不一致"
        assert core.verify_revisions(d)["ok"], f"{f}: revisions 不整合"
        # valid=None は bim.house 署名など openformats 検証対象外。失敗扱いにしない。
        assert all(s["valid"] is not False for s in core.verify_signatures(d)), f"{f}: 署名不正"


def test_large_reference_requires_store():
    """#6: 大きい参照音声は実体を保持する (store) か明示エラー。黙って捨てない。"""
    from openformats import voiceclone
    from openformats.store import Store
    import tempfile, os
    d = tempfile.mkdtemp()
    p = os.path.join(d, "big.wav")
    open(p, "wb").write(b"\x00" * 3_000_000)  # > 2MB
    voice = {"kind": "voice", "id": "v", "speaker": {"name": "t", "consent": "self"},
             "clone": {}}
    # store 無し → 明示エラー
    try:
        voiceclone.attach_reference(voice, p, text="hi", max_inline_bytes=2_000_000)
        assert False, "store 無しで大きい音声を黙って捨ててはいけない"
    except ValueError:
        pass
    # store 有り → 実体を保存し、復元できる
    st = Store(os.path.join(d, "store"))
    voiceclone.attach_reference(voice, p, text="hi", max_inline_bytes=2_000_000, store=st)
    rb = voiceclone.reference_bytes(voice, store=st)
    assert rb is not None and len(rb) == 3_000_000, "ストアから参照音声を復元できない"
    assert voiceclone.validate_clone(voice, store=st) == []


def test_export_schema_org_maps_kinds():
    sys.path.insert(0, str(ROOT / "tools"))
    import importlib
    export = importlib.import_module("export")
    music = {"kind": "music", "id": "x", "title": "T", "authors": [{"name": "A"}],
             "content_hash": "abc", "renditions": [{"path": "a.m4a", "sha256": "d"}]}
    ld = export.to_schema_org(music)
    assert ld["@type"] == "MusicComposition", ld
    assert ld["name"] == "T" and ld["sha256"] == "abc"
    assert ld["author"]["name"] == "A"
    assert ld["associatedMedia"][0]["contentUrl"] == "a.m4a"
    prod = export.to_schema_org({"kind": "product", "id": "p", "name": "P", "status": "live"})
    assert prod["@type"] == "Product" and prod["additionalProperty"]["value"] == "live"
    # 未知 kind は CreativeWork にフォールバック
    assert export.to_schema_org({"kind": "zzz", "id": "z"})["@type"] == "CreativeWork"


def test_export_schema_org_roundtrip():
    sys.path.insert(0, str(ROOT / "tools"))
    import importlib
    export = importlib.import_module("export")
    for kind in ("music", "radio", "movie", "book", "voice", "device", "product",
                 "article", "image", "event", "person", "place"):
        src = {"spec_version": "1.1.0", "kind": kind, "id": "w-1", "title": "T",
               "lang": "ja", "authors": [{"name": "A"}],
               "content_hash": "deadbeef",
               "renditions": [{"path": "a.bin", "format": "x", "sha256": "h"}]}
        back = export.from_schema_org(export.to_schema_org(src))
        assert back["kind"] == kind, f"{kind} -> {back['kind']}"
        assert back["id"] == "w-1" and back["title"] == "T"
        assert back["content_hash"] == "deadbeef"
        assert back["authors"][0]["name"] == "A"
        assert back["renditions"][0]["path"] == "a.bin"


def test_export_c2pa_manifest():
    sys.path.insert(0, str(ROOT / "tools"))
    import importlib
    export = importlib.import_module("export")
    data = {"kind": "music", "id": "x", "title": "T", "content_hash": "abc",
            "authors": [{"name": "A"}],
            "provenance": {"generator": {"name": "Suno", "version": "v4"},
                           "human_involvement": "ai-assisted",
                           "history": [{"at": "2026-01-01T00:00:00Z", "action": "create"}]},
            "renditions": [{"path": "a.m4a", "sha256": "d", "format": "m4a", "mime": "audio/mp4"}],
            "signatures": [{"alg": "Ed25519", "signer": "s", "public_key": "pk",
                            "signature": "sig", "signed_at": "2026-01-01T00:00:00Z"}]}
    man = export.to_c2pa(data)
    assert man["claim_generator"] == "Suno/v4"
    assert man["format"] == "audio/mp4"
    labels = {a["label"] for a in man["assertions"]}
    assert "c2pa.hash.data" in labels and "c2pa.actions" in labels
    assert man["assertions"][0]["data"]["hash"] == "abc"
    assert man["signature_info"][0]["alg"] == "Ed25519"
    assert man["ingredients"][0]["hash"]["hash"] == "d"
    # 署名・来歴の無い作品でも落ちない (空の assertions は省かれる)
    minimal = export.to_c2pa({"kind": "article", "id": "y"})
    assert "assertions" not in minimal or minimal["assertions"] == []


def test_export_musicxml_wellformed():
    sys.path.insert(0, str(ROOT / "tools"))
    import importlib, xml.etree.ElementTree as ET
    export = importlib.import_module("export")
    data = {"kind": "music", "id": "m1", "title": "T", "lang": "ja",
            "meta": {"bpm": 96, "key": "C major", "time_signature": "4/4"},
            "sections": [{"name": "verse"}, {"name": "chorus"}],
            "lyrics": [{"section": "verse",
                        "lines": ["one", "two", "three", "four"]}]}
    xml = export.to_musicxml(data)
    raw = xml.encode("utf-8")
    root = ET.fromstring(raw)
    assert root.tag.endswith("score-partwise"), root.tag
    # セクション数ぶんの小節があり、歌詞行が音符として出る
    assert raw.count(b"<measure ") >= 2
    assert raw.count(b"<lyric") >= 4


def test_export_otio_structure():
    sys.path.insert(0, str(ROOT / "tools"))
    import importlib
    export = importlib.import_module("export")
    data = {"kind": "movie", "id": "mv", "title": "T",
            "format": {"fps": 24},
            "timeline": [
                {"id": "v1", "type": "video", "clips": [
                    {"start_sec": 0, "duration_sec": 2.0, "src": "a.png"},
                    {"start_sec": 2, "duration_sec": 3.0, "src": "b.png"}]},
                {"id": "s1", "type": "subtitle", "clips": [
                    {"start_sec": 0, "duration_sec": 2.0, "text": "hi"}]}]}
    tl = export.to_otio(data)
    assert tl["OTIO_SCHEMA"] == "Timeline.1"
    assert tl["tracks"]["OTIO_SCHEMA"] == "Stack.1"
    tracks = tl["tracks"]["children"]
    assert len(tracks) == 2
    video = tracks[0]
    assert video["OTIO_SCHEMA"] == "Track.1" and video["kind"] == "Video"
    assert len(video["children"]) == 2
    c0 = video["children"][0]
    assert c0["OTIO_SCHEMA"] == "Clip.2"
    # 24fps で 2 秒 = 48 フレーム
    assert c0["source_range"]["duration"]["value"] == 48
    assert c0["source_range"]["duration"]["rate"] == 24
    sub = tracks[1]
    assert sub["kind"] == "Video"
    assert sub["children"][0]["metadata"]["openformats"]["subtitle_text"] == "hi"


def test_export_epub_valid_zip():
    sys.path.insert(0, str(ROOT / "tools"))
    import importlib, tempfile, zipfile, xml.etree.ElementTree as ET
    export = importlib.import_module("export")
    data = {"kind": "book", "id": "b1", "title": "本", "lang": "ja",
            "chapters": [{"id": "c1", "title": "第一章",
                          "blocks": [{"type": "paragraph", "text": "本文です。"}]}]}
    with tempfile.TemporaryDirectory() as d:
        out = pathlib.Path(d) / "b.epub"
        export.to_epub(data, out)
        z = zipfile.ZipFile(out)
        names = z.namelist()
        assert names[0] == "mimetype"
        assert z.read("mimetype") == b"application/epub+zip"
        assert "META-INF/container.xml" in names
        for n in names:
            if n.endswith((".opf", ".xhtml", ".xml")):
                ET.fromstring(z.read(n))


def test_export_pdf_structure():
    sys.path.insert(0, str(ROOT / "tools"))
    import importlib, tempfile
    export = importlib.import_module("export")
    data = {"kind": "book", "id": "b1", "title": "本", "lang": "ja",
            "chapters": [{"id": "c1", "title": "第一章",
                          "blocks": [{"type": "paragraph", "text": "本文です。"}]}]}
    with tempfile.TemporaryDirectory() as d:
        out = pathlib.Path(d) / "b.pdf"
        # フォント無しでも有効な PDF を生成できる
        export.to_pdf(data, out)
        raw = out.read_bytes()
    assert raw[:5] == b"%PDF-"
    assert b"%%EOF" in raw
    assert b"/Type /Catalog" in raw and b"/Type /Page" in raw


def test_c2pa_png_and_jpeg_roundtrip():
    sys.path.insert(0, str(ROOT / "tools"))
    import importlib, tempfile, struct, zlib
    export = importlib.import_module("export")
    man = {"title": "T", "format": "image/png"}
    jumbf = export.c2pa_jumbf_bytes(man)
    # 最小の PNG を組み立てる (1x1)
    def png_bytes():
        def chunk(ct, body):
            c = struct.pack(">I", len(body)) + ct + body
            return c + struct.pack(">I", zlib.crc32(ct + body) & 0xFFFFFFFF)
        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        idat = zlib.compress(b"\x00\x00\x00\x00")
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "x.png"
        p.write_bytes(png_bytes())
        export.embed_c2pa(p, jumbf)
        assert export.read_c2pa(p)["title"] == "T"
        # PNG として再び開ける
        data = p.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert data[-12:-8] == b"\x00\x00\x00\x00" or b"IEND" in data
        # JPEG は SOI/EOI を保ったまま埋め込み・読み戻しできる
        jp = pathlib.Path(d) / "x.jpg"
        jp.write_bytes(b"\xff\xd8\xff\xd9")  # 最小 JPEG (SOI+EOI)
        export.embed_c2pa(jp, jumbf)
        assert jp.read_bytes()[:2] == b"\xff\xd8"
        assert export.read_c2pa(jp)["title"] == "T"



def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{'FAIL' if failed else 'PASS'}: {failed} 失敗 / {len(fns)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
