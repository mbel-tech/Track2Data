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
    r = pair_by_regex(["k_both", "k_side"], r"(?P<key>k)_both|(?P<key2>zz)", r"(?P<key>k)_")
    assert r.both_roles == ["k_both"]
    assert r.pairs == []
    assert "k_both" not in r.top_ids + r.side_ids


def test_errors():
    r = pair_by_regex(["a_top", "a_side"], "(", SIDE)
    assert len(r.errors) == 1 and r.pairs == [] and r.top_ids == []
    r = pair_by_regex(["a_top", "a_side"], r"_top$", SIDE)
    assert len(r.errors) == 1 and r.pairs == []


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
