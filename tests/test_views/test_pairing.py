from track2data.views.pairing import (
    fish_labels,
    identity_map,
    pair_by_regex,
    validate_fish_map,
)

TOP = r"(?P<key>.+)_top$"
SIDE = r"(?P<key>.+)_side$"
NO_ID = "cannot match fish: this session has no stable identities"


def test_basic_pairing():
    r = pair_by_regex(["t1_top", "t1_side", "t2_top", "t2_side", "x"], TOP, SIDE)
    assert r.pairs == [("t1_top", "t1_side"), ("t2_top", "t2_side")]
    assert r.unpaired_top == []
    assert r.unpaired_side == []
    assert r.top_ids == ["t1_top", "t2_top"]
    assert r.side_ids == ["t1_side", "t2_side"]
    assert r.errors == []


def test_lone_top_unpaired():
    r = pair_by_regex(["t1_top", "t1_side", "t3_top"], TOP, SIDE)
    assert r.unpaired_top == ["t3_top"]
    assert r.pairs == [("t1_top", "t1_side")]


def test_ambiguous_key():
    r = pair_by_regex(["a_top", "a_top2", "a_side"], r"(?P<key>a)_top", SIDE)
    assert r.ambiguous_keys == ["a"]
    assert r.pairs == []
    assert r.unpaired_top == ["a_top", "a_top2"]
    assert r.unpaired_side == ["a_side"]


def test_both_roles():
    r = pair_by_regex(["k_both", "k_side"], r"(?P<key>k)_both", r"(?P<key>k)_")
    assert r.both_roles == ["k_both"]
    assert r.pairs == []
    assert "k_both" not in r.top_ids + r.side_ids


def test_errors():
    r = pair_by_regex(["a_top", "a_side"], "(", SIDE)
    assert len(r.errors) == 1 and r.errors[0].startswith("top regex")
    assert r.pairs == [] and r.top_ids == []
    assert r.side_ids == ["a_side"] and r.unpaired_side == ["a_side"]
    r = pair_by_regex(["a_top", "a_side"], r"_top$", SIDE)
    assert len(r.errors) == 1 and r.errors[0].startswith("top regex")
    assert r.pairs == [] and r.side_ids == ["a_side"]


def test_empty_or_missing_key_is_not_a_candidate():
    ids = ["_top", "_side", "_x_top", "t1_top", "t1_side"]
    for top in (r"(?P<key>.*)_top$", r"(?P<key>\d+)?_top$"):
        r = pair_by_regex(["_top", "_side", "t1_side"], top, r"(?P<key>.*)_side$")
        assert r.top_ids == [] and r.pairs == []
        assert r.ambiguous_keys == [] and r.errors == []
        assert r.side_ids == ["t1_side"]
    r = pair_by_regex(ids, r"(?P<key>.*)_top$", r"(?P<key>.*)_side$")
    assert r.pairs == [("t1_top", "t1_side")]
    assert r.ambiguous_keys == [] and r.errors == []
    assert "_top" not in r.top_ids and "_side" not in r.side_ids


def test_empty_labels_and_no_overlap():
    assert identity_map([], []) == ({}, [])
    assert identity_map(["a"], ["b"]) == ({}, ["a", "b"])
    assert _v({}, [], []) == []


def test_unknown_labels_deduped():
    msgs = _v({"a": "z", "b": "z", "q": "x", "r": "x"}, ["a", "b"], ["x"])
    assert msgs.count("unknown side fish: z") == 1
    assert msgs.count("unknown top fish: q") == 1
    assert msgs.count("unknown top fish: r") == 1
    assert _v({"q": "x", "q2": "x"}, ["a"], ["x"]).count("unknown top fish: q") == 1


def test_empty_regex_not_set():
    r = pair_by_regex(["a_top"], "", "")
    assert r.pairs == [] and r.errors == [] and r.top_ids == []


def test_fish_labels():
    assert fish_labels(None, 3) == ["0", "1", "2"]
    assert fish_labels(["a", "b"], 2) == ["a", "b"]


def test_identity_map():
    assert identity_map(["a", "b"], ["b", "c"]) == ({"b": "b"}, ["a", "c"])


def _v(m, t, s, tf=False, sf=False):
    return validate_fish_map(m, t, s, top_identity_free=tf, side_identity_free=sf)


def test_validate():
    msgs = _v({"a": "x", "b": "x"}, ["a", "b"], ["x"])
    assert "duplicate side fish: x" in msgs
    assert "2 top fish vs 1 side fish" in msgs
    assert "unknown top fish: z" in _v({"z": "x"}, ["a"], ["x"])
    assert "unknown side fish: z" in _v({"a": "z"}, ["a"], ["x"])
    assert _v({"a": "x"}, ["a"], ["x"], tf=True, sf=True) == [NO_ID]
    assert _v({"a": "x"}, ["a"], ["x"]) == []
