"""Qt-free application of a panel (a rectangle of the video) to a session.

A 'One video, two panels' project cuts one shared video into a top and a side view. The tracker
result covers the whole frame; ``apply_panel`` turns it into a session of one view:

* kept: animals with at least ``MIN_COVERAGE`` of their valid positions inside the panel (for a
  session without stable identities: every slot with a position left inside), filtered together
  in every per-animal field (``raw_xy``, ``body_length_px``, ``id_probabilities``, identity labels
  and colours, the pose skeleton);
* shifted: every whole-frame pixel coordinate moves to panel coordinates (panel top-left is
  (0, 0)): ``raw_xy`` (positions outside the panel become NaN), skeleton points, ``setup_points``
  pairs, ROI polygon vertices and length-calibration end points;
* dropped (set to None): per-animal or whole-frame data that cannot be cut, ``bbox_table``,
  ``bbox_summary``, ``identities_groups``, ``fragments`` and the ROI mask path; per-animal data
  whose length does not match the animal count is dropped too;
* left alone: everything else, including ``background_image_path`` (a whole-frame image that
  consumers crop) and ``blob_body_length_source_file`` (the lengths are filtered, not recomputed).

Panel bounds are half-open (``x <= px < x + width``), so a position on the line shared by two
panels belongs to one panel only. Coordinate pairs are shifted at any nesting depth, so
idtracker.ai's ``{"BP1": [[x, y]]}`` landmarks keep their shape.

The input session is never modified.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from track2data.core.models import PanelRect, Session
from track2data.views.pairing import fish_labels

#: An animal is kept when at least this share of its valid positions lies inside the panel.
MIN_COVERAGE = 0.5
#: Below this share the editor flags the animal as partly outside the panel.
LOW_COVERAGE = 0.9

_EPS = 1e-6


@dataclass(frozen=True)
class AnimalCoverage:
    index: int
    label: str
    share_inside: float
    n_valid: int


def _check_fits(session: Session, rect: PanelRect) -> None:
    """Raise ValueError when the panel is not inside the video (unknown size 0 is not checked)."""
    w, h = session.video.width_px, session.video.height_px
    if w > 0 and rect.x + rect.width > w + _EPS:
        raise ValueError(
            f"The panel (x {rect.x:g} to {rect.x + rect.width:g}) is wider than the {w} px video"
        )
    if h > 0 and rect.y + rect.height > h + _EPS:
        raise ValueError(
            f"The panel (y {rect.y:g} to {rect.y + rect.height:g}) is taller than the {h} px video"
        )


def _masks(raw_xy: np.ndarray, rect: PanelRect) -> tuple[np.ndarray, np.ndarray]:
    """(valid, inside) boolean arrays of shape (n_frames, n_animals); bounds are half-open."""
    x, y = raw_xy[..., 0], raw_xy[..., 1]
    valid = np.isfinite(x) & np.isfinite(y)
    with np.errstate(invalid="ignore"):
        inside = (
            valid
            & (x >= rect.x)
            & (x < rect.x + rect.width)
            & (y >= rect.y)
            & (y < rect.y + rect.height)
        )
    return valid, inside


def panel_coverage(session: Session, rect: PanelRect) -> list[AnimalCoverage]:
    """Per animal, the share of its valid positions inside the panel (0 when it has none)."""
    _check_fits(session, rect)
    valid, inside = _masks(session.raw_xy, rect)
    n_valid = valid.sum(axis=0)
    n_inside = inside.sum(axis=0)
    labels = fish_labels(session.identities_labels, session.raw_xy.shape[1])
    return [
        AnimalCoverage(
            index=i,
            label=labels[i] if i < len(labels) else str(i),
            share_inside=float(n_inside[i] / n_valid[i]) if n_valid[i] else 0.0,
            n_valid=int(n_valid[i]),
        )
        for i in range(session.raw_xy.shape[1])
    ]


def _pick(seq: list | None, keep: list[int], n_animals: int) -> list | None:
    """Filter a per-animal list; data that does not have one entry per animal is dropped (None)."""
    if seq is None or len(seq) != n_animals:
        return None
    return [seq[i] for i in keep]


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool)


def _shift_points(value: Any, dx: float, dy: float) -> Any:
    """Shift every numeric [x, y] pair found at any depth, keeping nesting and container type."""
    if isinstance(value, np.ndarray):
        if value.dtype.kind in "iuf" and value.ndim >= 1 and value.shape[-1] == 2:
            return value.astype(float) - np.array([dx, dy])
        return value
    if isinstance(value, (list, tuple)):
        if len(value) == 2 and all(_is_num(v) for v in value):
            out = [float(value[0]) - dx, float(value[1]) - dy]
        else:
            out = [_shift_points(v, dx, dy) for v in value]
        return tuple(out) if isinstance(value, tuple) else out
    return value


def _shift_roi(
    roi_list: list[dict[str, Any]] | None, dx: float, dy: float
) -> list[dict[str, Any]] | None:
    if roi_list is None:
        return None
    out = []
    for roi in roi_list:
        new = dict(roi)
        verts = [(float(vx) - dx, float(vy) - dy) for vx, vy in roi.get("vertices", [])]
        new["vertices"] = verts
        if "raw" in new:
            sign = roi.get("sign", "+")
            new["raw"] = f"{sign} Polygon {[[vx, vy] for vx, vy in verts]}"
        out.append(new)
    return out


def apply_panel(session: Session, rect: PanelRect) -> Session:
    """Return the session cut to ``rect``, in panel coordinates (see the module docstring).

    Raises ValueError when the panel does not fit inside the video.
    """
    _check_fits(session, rect)
    raw = session.raw_xy
    valid, inside = _masks(raw, rect)
    n_valid = valid.sum(axis=0)
    n_inside = inside.sum(axis=0)
    if session.has_stable_identities:
        share = np.divide(n_inside, n_valid, out=np.zeros(raw.shape[1]), where=n_valid > 0)
        keep_mask = (n_valid > 0) & (share >= MIN_COVERAGE)
    else:
        keep_mask = n_inside > 0
    keep = [int(i) for i in np.flatnonzero(keep_mask)]
    n = raw.shape[1]

    new_xy = raw[:, keep, :].astype(float, copy=True)
    new_xy[~inside[:, keep]] = np.nan
    new_xy[..., 0] -= rect.x
    new_xy[..., 1] -= rect.y

    update: dict[str, Any] = {
        "raw_xy": new_xy,
        "n_animals": len(keep),
        "video": session.video.model_copy(
            update={"width_px": round(rect.width), "height_px": round(rect.height)}
        ),
        "identities_labels": _pick(session.identities_labels, keep, n),
        "identities_colors": _pick(session.identities_colors, keep, n),
        "bbox_table": None,
        "bbox_summary": None,
        "identities_groups": None,
        "fragments": None,
        "roi_mask_path": None,
    }
    # Per-animal data of the wrong length cannot be matched to animals: dropped, not guessed.
    bl = session.body_length_px
    update["body_length_px"] = (
        np.asarray(bl)[keep] if bl is not None and np.asarray(bl).shape[0] == n else None
    )
    ip = session.id_probabilities
    update["id_probabilities"] = (
        np.asarray(ip)[:, keep] if ip is not None and np.asarray(ip).shape[1] == n else None
    )
    if session.setup_points is not None:
        update["setup_points"] = {
            k: _shift_points(v, rect.x, rect.y) for k, v in session.setup_points.items()
        }
    if session.roi_list is not None:
        update["roi_list"] = _shift_roi(session.roi_list, rect.x, rect.y)
    if session.length_calibrations is not None:
        update["length_calibrations"] = [
            {
                **c,
                **{
                    k: _shift_points(c[k], rect.x, rect.y) for k in ("point_A", "point_B") if k in c
                },
            }
            for c in session.length_calibrations
        ]
    if session.keypoints is not None:
        kp = session.keypoints
        kxy = kp.xy[:, keep].astype(float, copy=True)
        k_in = (
            (kxy[..., 0] >= rect.x)
            & (kxy[..., 0] < rect.x + rect.width)
            & (kxy[..., 1] >= rect.y)
            & (kxy[..., 1] < rect.y + rect.height)
        )  # NaN compares False, so missing points stay outside
        kxy[~k_in] = np.nan
        kxy[..., 0] -= rect.x
        kxy[..., 1] -= rect.y
        conf = None
        if kp.confidence is not None:
            conf = kp.confidence[:, keep].astype(float, copy=True)
            conf[~k_in] = np.nan
        update["keypoints"] = kp.model_copy(update={"xy": kxy, "confidence": conf})
    return session.model_copy(update=update)


def preset_rects(
    preset: Literal["left_right", "top_bottom"],
    frame_width: float,
    frame_height: float,
    split: float = 0.5,
    first_is_top: bool = True,
) -> tuple[PanelRect, PanelRect]:
    """Cut the frame in two at ``split`` (share of the width or height given to the first part).

    Returns ``(top_rect, side_rect)``; the first part (left or upper) is the top view when
    ``first_is_top`` is true, else the side view.
    """
    if preset == "left_right":
        w1 = frame_width * split
        first = PanelRect(x=0, y=0, width=w1, height=frame_height)
        second = PanelRect(x=w1, y=0, width=frame_width - w1, height=frame_height)
    else:
        h1 = frame_height * split
        first = PanelRect(x=0, y=0, width=frame_width, height=h1)
        second = PanelRect(x=0, y=h1, width=frame_width, height=frame_height - h1)
    return (first, second) if first_is_top else (second, first)
