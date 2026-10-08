"""Reader options: validation, defaults and the two coded errors."""

from __future__ import annotations

from pathlib import Path

import pytest

from track2data.core.errors import ImportError_
from track2data.readers.params import (
    ReaderParameter,
    parse_assignments,
    parse_value,
    resolve_options,
)

PARAMS = (
    ReaderParameter(name="fps", label="Frame rate", kind="float", required=True, minimum=0.001),
    ReaderParameter(
        name="cutoff", label="Cutoff", kind="float", default=0.6, minimum=0, maximum=1
    ),
    ReaderParameter(
        name="variant", label="Variant", kind="choice", default="raw", choices=("raw", "filtered")
    ),
    ReaderParameter(name="parts", label="Parts", kind="multichoice", choices=("a", "b", "c")),
    ReaderParameter(name="keep", label="Keep", kind="bool", default=True),
    ReaderParameter(name="n", label="N", kind="int", default=3),
)


def test_defaults_are_filled_and_given_values_win() -> None:
    out = resolve_options("t", PARAMS, {"fps": 30})
    assert out == {"fps": 30, "cutoff": 0.6, "variant": "raw", "parts": None, "keep": True, "n": 3}


def test_given_values_override_defaults() -> None:
    out = resolve_options("t", PARAMS, {"fps": 25.5, "cutoff": 0.9, "variant": "filtered"})
    assert out["fps"] == 25.5
    assert out["cutoff"] == 0.9
    assert out["variant"] == "filtered"


def test_no_options_at_all_still_demands_the_required_one() -> None:
    with pytest.raises(ImportError_) as err:
        resolve_options("t", PARAMS, None)
    assert err.value.code == "READER_OPTION_MISSING"


@pytest.mark.parametrize("given", [{}, {"fps": None}])
def test_a_missing_required_option_names_it_and_never_defaults(given: dict) -> None:
    with pytest.raises(ImportError_) as err:
        resolve_options("t", PARAMS, given)
    assert err.value.code == "READER_OPTION_MISSING"
    assert err.value.subject == "fps"
    assert err.value.remediation


@pytest.mark.parametrize(
    "given",
    [
        {"fps": 30, "nope": 1},  # unknown name
        {"fps": "fast"},  # wrong type
        {"fps": True},  # bool is not a number
        {"fps": 0},  # below minimum
        {"fps": 30, "cutoff": 2},  # above maximum
        {"fps": 30, "variant": "weird"},  # not a choice
        {"fps": 30, "parts": ["a", "z"]},  # not a subset of the choices
        {"fps": 30, "parts": "a"},  # a string is not a list of choices
        {"fps": 30, "n": 2.5},  # int expected
        {"fps": 30, "keep": "yes"},  # bool expected
        {"fps": float("nan")},  # not finite
        {"fps": float("inf")},  # not finite
    ],
)
def test_bad_values_are_invalid(given: dict) -> None:
    with pytest.raises(ImportError_) as err:
        resolve_options("t", PARAMS, given)
    assert err.value.code == "READER_OPTION_INVALID"
    assert err.value.remediation


def test_a_reader_without_parameters_accepts_no_options() -> None:
    assert resolve_options("t", (), None) == {}
    assert resolve_options("t", (), {}) == {}
    with pytest.raises(ImportError_) as err:
        resolve_options("t", (), {"fps": 30})
    assert err.value.code == "READER_OPTION_INVALID"
    assert err.value.subject == "fps"


def test_the_error_message_names_the_reader() -> None:
    with pytest.raises(ImportError_) as err:
        resolve_options("deeplabcut", PARAMS, {})
    assert "deeplabcut" in str(err.value)


# ── text to typed values (the CLI's --option name=value) ─────────────────────


def _spec(name: str) -> ReaderParameter:
    return next(p for p in PARAMS if p.name == name)


@pytest.mark.parametrize(
    ("name", "text", "expected"),
    [
        ("n", "30", 30),
        ("fps", "25", 25.0),
        ("fps", " 2.5e1 ", 25.0),
        ("keep", "true", True),
        ("keep", "No", False),
        ("keep", "1", True),
        ("keep", "off", False),
        ("variant", "filtered", "filtered"),
        ("parts", "a,b", ["a", "b"]),
        ("parts", " a , c ", ["a", "c"]),
    ],
)
def test_text_becomes_the_value_the_parameter_declares(
    name: str, text: str, expected: object
) -> None:
    assert parse_value(_spec(name), text) == expected


def test_text_and_path_parameters_keep_their_text() -> None:
    free_text = ReaderParameter(name="s", label="S", kind="str")
    a_path = ReaderParameter(name="p", label="P", kind="path")
    assert parse_value(free_text, "a b") == "a b"
    assert parse_value(a_path, "x/y.csv") == Path("x/y.csv")


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("n", "3.5"),  # not whole
        ("n", "three"),
        ("fps", "fast"),
        ("fps", "nan"),
        ("fps", "inf"),
        ("fps", ""),
        ("keep", "maybe"),
        ("variant", "weird"),
        ("parts", "a,z"),
    ],
)
def test_text_that_is_not_that_kind_of_value_is_invalid_and_names_the_option(
    name: str, text: str
) -> None:
    with pytest.raises(ImportError_) as err:
        parse_value(_spec(name), text)
    assert err.value.code == "READER_OPTION_INVALID"
    assert err.value.subject == name
    assert err.value.remediation


def test_a_range_is_checked_after_parsing_not_before() -> None:
    # parse_value only turns text into a value; resolve_options owns the range rule
    assert parse_value(_spec("fps"), "0") == 0.0
    with pytest.raises(ImportError_):
        resolve_options("t", PARAMS, {"fps": parse_value(_spec("fps"), "0")})


def test_assignments_are_split_on_the_first_equals_sign_only() -> None:
    out = parse_assignments(PARAMS, ["fps=30", "variant=raw"])
    assert out == {"fps": 30.0, "variant": "raw"}
    free = (ReaderParameter(name="label", label="L", kind="str"),)
    assert parse_assignments(free, ["label=a=b"]) == {"label": "a=b"}


@pytest.mark.parametrize("bad", ["fps", "=30", "nope=1"])
def test_an_assignment_that_is_malformed_or_names_no_option_is_invalid(bad: str) -> None:
    with pytest.raises(ImportError_) as err:
        parse_assignments(PARAMS, [bad])
    assert err.value.code == "READER_OPTION_INVALID"


def test_the_same_option_given_twice_is_invalid_rather_than_last_one_wins() -> None:
    with pytest.raises(ImportError_) as err:
        parse_assignments(PARAMS, ["fps=30", "fps=60"])
    assert err.value.code == "READER_OPTION_INVALID"
    assert err.value.subject == "fps"



class TestAChoiceWhoseValuesOnlyTheFilesKnow:
    """Which keypoint, which individual: the list exists only once a file has been looked at.

    The class-level spec (what ``read`` validates against) cannot list them, so empty ``choices``
    means "open set: the reader checks the value against the file". The scan's per-file spec fills
    the choices in for the dialog.
    """

    OPEN_CHOICE = ReaderParameter(name="keypoint", label="Keypoint", kind="choice")
    OPEN_MULTI = ReaderParameter(name="individuals", label="Animals", kind="multichoice")

    def test_any_value_is_accepted_for_the_reader_to_check(self) -> None:
        out = resolve_options("r", [self.OPEN_CHOICE, self.OPEN_MULTI], {
            "keypoint": "snout", "individuals": ["a", "b"],
        })  # fmt: skip
        assert out == {"keypoint": "snout", "individuals": ["a", "b"]}

    def test_it_is_still_optional_and_defaults_to_nothing(self) -> None:
        assert resolve_options("r", [self.OPEN_CHOICE], {}) == {"keypoint": None}

    def test_a_string_is_still_not_a_list(self) -> None:
        with pytest.raises(ImportError_):
            resolve_options("r", [self.OPEN_MULTI], {"individuals": "a"})

    def test_the_command_line_form_is_accepted_too(self) -> None:
        assert parse_value(self.OPEN_CHOICE, "snout") == "snout"
        assert parse_value(self.OPEN_MULTI, "a, b") == ["a", "b"]

    def test_a_closed_choice_is_still_closed(self) -> None:
        closed = ReaderParameter(name="v", label="V", kind="choice", choices=("a",))
        with pytest.raises(ImportError_):
            resolve_options("r", [closed], {"v": "b"})
        with pytest.raises(ImportError_):
            parse_value(closed, "b")
