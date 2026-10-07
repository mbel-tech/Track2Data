"""The value types a scan reports: ordered confidence, immutable candidates and detections."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from track2data.readers.detection import Confidence, Detection, SessionCandidate
from track2data.readers.params import ProposedValue, ReaderParameter


def test_confidence_is_ordered() -> None:
    assert Confidence.LOW < Confidence.MEDIUM < Confidence.HIGH
    assert sorted([Confidence.HIGH, Confidence.LOW, Confidence.MEDIUM], reverse=True) == [
        Confidence.HIGH,
        Confidence.MEDIUM,
        Confidence.LOW,
    ]


def test_a_candidate_is_immutable_and_defaults_to_no_files_or_warnings(tmp_path: Path) -> None:
    candidate = SessionCandidate(session_id="s1", source=tmp_path)
    assert candidate.files == ()
    assert candidate.warnings == ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        candidate.session_id = "other"  # type: ignore[misc]


def test_a_detection_defaults_are_conservative() -> None:
    detection = Detection(
        reader="deeplabcut", display_name="DeepLabCut", confidence=Confidence.HIGH
    )
    assert detection.evidence == ()
    assert detection.sessions == ()
    assert detection.parameters == ()
    assert detection.proposed == {}
    # A detection claims nothing about real-data verification unless its reader says so.
    assert detection.verification == "synthetic_only"
    with pytest.raises(dataclasses.FrozenInstanceError):
        detection.confidence = Confidence.LOW  # type: ignore[misc]


def test_each_detection_gets_its_own_proposed_mapping() -> None:
    a = Detection(reader="a", display_name="A", confidence=Confidence.LOW)
    b = Detection(reader="b", display_name="B", confidence=Confidence.LOW)
    assert a.proposed is not b.proposed


def test_a_detection_carries_parameters_and_where_each_proposed_value_came_from(
    tmp_path: Path,
) -> None:
    fps = ReaderParameter(name="fps", label="Frame rate", kind="float", required=True)
    detection = Detection(
        reader="deeplabcut",
        display_name="DeepLabCut",
        confidence=Confidence.MEDIUM,
        evidence=("14 files with a scorer header",),
        sessions=(SessionCandidate(session_id="s1", source=tmp_path / "a.csv"),),
        parameters=(fps,),
        proposed={"fps": ProposedValue(value=30.0, source="video")},
    )
    assert detection.proposed["fps"].source == "video"
    assert detection.parameters[0].name == "fps"
    assert detection.sessions[0].source.name == "a.csv"
