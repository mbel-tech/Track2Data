"""
SessionFacts — a derived, in-memory-only cache of facts read straight
from a session's own trajectory/session.json files.

Populated from the same background read_session() probe that
ProjectStore.add_session() already submits to fill in
SessionRef.has_stable_identities (see project_store.py's
_on_identity_probe_finished) -- this cache costs nothing extra to
build, since the read already happens, on a background thread, for
every added session folder. Before this existed the probe's full
Session result was read once for that one boolean and then discarded.

Deliberately NOT stored on SessionRef. SessionRef is part of
ProjectManifest, which is serialised verbatim into the project's
.t2d.json file -- anything added there becomes persisted, versioned
project state. SessionFacts holds derived information that is always
re-readable from the session folder, so it belongs in memory only,
never in the manifest schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from track2data.core.models import Session


@dataclass(frozen=True)
class SessionFacts:
    """Read-only facts about one session, probed off its trajectory files.

    Everything here can be re-derived by re-reading the session folder;
    nothing here is user-editable state.
    """

    session_id: str
    reader: str
    fps: float
    n_frames: int
    n_animals: int
    width_px: int
    height_px: int
    has_stable_identities: bool
    # What the tracker itself declared (Session.track_wo_identities), as
    # opposed to has_stable_identities, which also folds in coverage
    # heuristics. None = the source didn't report it. The *user's* override
    # of this lives on SessionRef, not here: it is authored state, not a
    # fact re-readable from the folder.
    track_wo_identities: bool | None
    idtrackerai_version: str | None
    # idtracker.ai's px-to-real-unit ratio (from the validator's
    # length-calibration tool); None means this session was never
    # calibrated. See track2data/calibration/session_unit.py.
    length_unit: float | None
    # Named validator landmarks (e.g. {"feeder": [x, y]}); guides for
    # zone definition, not auto-polygons -- see ui/zones_screen.py.
    setup_points: dict[str, Any] | None
    # Parsed signed polygons from session.json's roi_list, ready for
    # track2data.zones.io.zone_set_from_roi_list().
    roi_list: list[dict[str, Any]] | None
    has_body_length: bool
    # Path only, not decoded pixel data (see readers/idtrackerai/
    # preprocessing.py's module docstring) -- the zone canvas decodes
    # it directly via QImage when it needs a backdrop.
    background_image_path: Path | None

    @classmethod
    def from_session(cls, session: Session) -> SessionFacts:
        """Build from the full engine-side Session a background probe
        returns, keeping only what the GUI needs to display or route on."""
        return cls(
            session_id=session.session_id,
            reader=session.reader,
            fps=session.video.fps,
            n_frames=session.video.n_frames,
            n_animals=session.n_animals,
            width_px=session.video.width_px,
            height_px=session.video.height_px,
            has_stable_identities=session.has_stable_identities,
            track_wo_identities=session.track_wo_identities,
            idtrackerai_version=session.idtrackerai_version,
            length_unit=session.length_unit,
            setup_points=session.setup_points,
            roi_list=session.roi_list,
            has_body_length=session.body_length_px is not None,
            background_image_path=session.background_image_path,
        )
