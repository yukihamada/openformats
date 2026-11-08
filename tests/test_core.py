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
