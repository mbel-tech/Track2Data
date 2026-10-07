"""Reader options: validation, defaults and the two coded errors."""

from __future__ import annotations

import pytest

from track2data.core.errors import ImportError_
from track2data.readers.params import ReaderParameter, resolve_options

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
