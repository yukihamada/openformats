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
    print(f"\n{'FAIL' if failed else 'PASS'}: {failed} 失敗 / {len(fns)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
