"""Helpers shared by the readers of native 3-D tracker files (Anipose, DeepLabCut-3D).

These files hold positions in a length unit (mm, cm, m or inches), with three axes and no pixel
frame. The readers convert the unit when reading, choose the axis that is "up", and hand the
other two to the pipeline as the horizontal plane; ``z`` is the vertical coordinate, absolute and
in the project's length unit.

A wrong unit silently scales every speed, so ``unit`` is a required option: a reader may *propose*
one (Anipose proposes mm) but never fills it in on its own.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

import numpy as np

from track2data.readers.assemble import Reduction, reduce_keypoints, to_nan
from track2data.readers.params import ReaderParameter

#: Reader ids that produce native 3-D sessions. Availability code uses this constant so it does not
#: have to import the reader registry.
NATIVE_3D_READERS: frozenset[str] = frozenset({"anipose", "deeplabcut_3d"})

#: Length of one unit, in metres.
UNIT_FACTORS_M: dict[str, float] = {"mm": 0.001, "cm": 0.01, "m": 1.0, "in": 0.0254}

#: The same factors as exact ratios (relative to a millimetre), so a conversion is one integer
#: multiplication and one division and 19 mm is exactly 1.9 cm.
_RATIO_TO_MM: dict[str, Fraction] = {
    "mm": Fraction(1),
    "cm": Fraction(10),
    "m": Fraction(1000),
    "in": Fraction(254, 10),
}

UNITS: tuple[str, ...] = tuple(UNIT_FACTORS_M)
AXES: tuple[str, ...] = ("x", "y", "z")


def manifest_native_3d(manifest: Any) -> bool:
    """Whether *manifest* is a native 3-D project: any of its sessions comes from a native reader.

    Decided from the saved reader names alone (no file is read). A project never mixes the two
    kinds (``Engine.register_native_import`` refuses it), so one native session decides it.
    """
    return any(ref.reader in NATIVE_3D_READERS for ref in manifest.sessions)


def convert_units(values: np.ndarray, unit: str, target: str) -> np.ndarray:
    """*values* given in *unit*, expressed in *target* (a new float64 array).

    ``coordinate x factor(unit) / factor(target)``, computed as an exact integer ratio (multiply by
    the numerator, divide by the denominator). Raises ``ValueError`` for an unknown unit.
    """
    for name in (unit, target):
        if name not in UNIT_FACTORS_M:
            raise ValueError(f"unknown length unit {name!r}; expected one of {list(UNITS)}")
    out = np.array(values, dtype=np.float64, copy=True)
    if unit == target:
        return out
    ratio = _RATIO_TO_MM[unit] / _RATIO_TO_MM[target]
    return out * ratio.numerator / ratio.denominator


def horizontal_axes(vertical_axis: str) -> tuple[int, int]:
    """The two file axes that are not vertical, in file order."""
    if vertical_axis not in AXES:
        raise ValueError(f"vertical_axis must be one of {list(AXES)}, got {vertical_axis!r}")
    first, second = (i for i in range(3) if AXES[i] != vertical_axis)
    return first, second


def native_parameters(unit_default: str | None) -> tuple[ReaderParameter, ...]:
    """The options of a native 3-D reader, in the order the dialog shows them.

    *unit_default* is only a hint for the help text (Anipose files do not state their unit, mm is
    the usual one): ``unit`` stays required, so a read without it is an error, never a guess.
    """
    hint = (
        f" {unit_default} is the usual one for this tool, but check it against your calibration."
        if unit_default
        else ""
    )
    return (
        ReaderParameter(
            name="fps",
            label="Frame rate (frames per second)",
            kind="float",
            required=True,
            minimum=0.001,
            help="These files do not record the video's frame rate.",
        ),
        ReaderParameter(
            name="unit",
            label="Unit of the coordinates in the file",
            kind="choice",
            required=True,
            choices=UNITS,
            help="The file does not state its unit; a wrong one scales every speed." + hint,
        ),
        ReaderParameter(
            name="target_unit",
            label="Project length unit",
            kind="choice",
            default="cm",
            choices=UNITS,
            help="Coordinates are converted to this unit when read. Every session of a project "
            "must use the same one.",
        ),
        ReaderParameter(
            name="keypoint",
            label="Animal position from",
            kind="choice",
            help="The keypoint that stands for the animal. Left unset, the keypoint seen "
            "most often after the likelihood cutoff is used.",
        ),
        ReaderParameter(
            name="likelihood_cutoff",
            label="Score cutoff",
            kind="float",
            default=0.0,
            minimum=0.0,
            help="Positions with a score below this are treated as missing. 0 keeps everything.",
        ),
        ReaderParameter(
            name="vertical_axis",
            label="Vertical axis of the file",
            kind="choice",
            default="z",
            choices=AXES,
            help="Which axis points up. The other two become the horizontal plane.",
        ),
        ReaderParameter(
            name="flip",
            label="Flip the vertical axis",
            kind="bool",
            default=False,
            help="Tick when the vertical axis points down.",
        ),
        ReaderParameter(
            name="keep_skeleton",
            label="Keep all keypoints",
            kind="bool",
            default=True,
            help="Store every keypoint beside the one used (no metric reads them).",
        ),
    )


def reduce_native(
    xy3: np.ndarray,
    names: list[str],
    confidence: np.ndarray | None,
    *,
    keypoint: str | None,
    cutoff: float | None,
    vertical_axis: str,
    flip: bool,
) -> tuple[Reduction, np.ndarray]:
    """One keypoint per animal from ``xy3`` (F, A, K, 3), and its vertical coordinate.

    The reduction's ``raw_xy`` is the horizontal plane; ``z`` is the chosen keypoint's coordinate on
    the vertical axis, ``(F, A)``, negated when *flip*, and NaN wherever the position is missing
    (including below the cutoff).

    Only ``raw_xy`` and ``z`` follow *vertical_axis* and *flip*. The stored skeleton (the caller's
    ``xy3``) keeps the file's three axes as they are: not permuted and not flipped.
    """
    xyz = np.asarray(xy3)
    if xyz.ndim != 4 or xyz.shape[3] != 3:
        raise ValueError(f"xy3 must be (frames, animals, keypoints, 3), got {xyz.shape}")
    reduction = reduce_keypoints(
        xyz,
        names,
        confidence,
        keypoint=keypoint,
        cutoff=cutoff,
        plane=horizontal_axes(vertical_axis),
    )
    chosen = names.index(reduction.selection.keypoint)
    z = to_nan(xyz[:, :, chosen, AXES.index(vertical_axis)])
    z[~np.isfinite(reduction.raw_xy).all(axis=-1)] = np.nan
    if flip:
        z = -z
    return reduction, z
