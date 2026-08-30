#!/usr/bin/env python3
"""Generate the example idtracker.ai session under ``examples/tiny_session/``.

Run this to regenerate the committed example, or to make a bigger one to
experiment with:

    python examples/make_example_session.py                 # the committed size
    python examples/make_example_session.py --minutes 10    # something longer

Two deliberate choices about what it writes:

**CSV, not the pickled ``.npy``.** idtracker.ai can write either. A `.npy`
trajectory is a pickle, and loading one executes whatever code it contains
-- so committing one to a public repository would ship an execution vector
as a "here, try this" example, and Track2Data would (correctly) refuse to
open it without an explicit opt-in. The CSV bundle is inert, diffable, and
readable in any text editor, which is what an example should be. See
``SECURITY.md``.

**Simulated behaviour, not random noise.** Four fish in a circular arena,
two of which prefer the outer wall (thigmotaxis) while two roam the centre,
all with a correlated random walk and occasional freezing bouts. Random
positions would exercise the code but teach nothing: every metric would come
out at its null value, and the example could not show what a *result* looks
like.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

FPS = 30.0
ARENA_CENTRE = np.array([500.0, 500.0])
ARENA_RADIUS = 450.0
BODY_LENGTH_PX = 40.0
PX_PER_CM = 10.0


def simulate(
    n_frames: int, n_animals: int = 4, seed: int = 20260830
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(xy, id_probabilities)`` for a plausible four-fish session.

    Animals 0 and 1 hug the wall, 2 and 3 use the whole arena. Everyone
    freezes occasionally. The point is that the exported metrics come out
    *different between individuals* in a way a reader can interpret, rather
    than all landing on the same null value.
    """
    rng = np.random.default_rng(seed)
    xy = np.zeros((n_frames, n_animals, 2), dtype=np.float64)

    for k in range(n_animals):
        wall_hugger = k < 2
        preferred_radius = ARENA_RADIUS * (0.85 if wall_hugger else 0.35)

        angle = rng.uniform(0, 2 * np.pi)
        radius = preferred_radius
        heading = rng.uniform(0, 2 * np.pi)
        speed = 3.0

        # Freezing bouts: geometric-ish runs of near-zero speed, which is
        # what IL-7 exists to count.
        frozen_until = -1

        for t in range(n_frames):
            if t > frozen_until and rng.random() < 0.002:
                frozen_until = t + int(rng.integers(15, 90))
            moving = t > frozen_until

            heading += rng.normal(0.0, 0.25)
            step = speed if moving else 0.0

            angle += (step / max(radius, 1.0)) * np.cos(heading) * 0.5
            radius += step * np.sin(heading) * 0.3
            # Pull back toward the preferred band, and keep inside the arena.
            radius += (preferred_radius - radius) * 0.02
            radius = float(np.clip(radius, 5.0, ARENA_RADIUS - BODY_LENGTH_PX / 2))

            xy[t, k] = ARENA_CENTRE + radius * np.array([np.cos(angle), np.sin(angle)])

    # A few short dropouts, as any real tracker produces. Kept under the
    # default max_gap_frames so gap_fill takes them and D-11 has something
    # non-zero to report.
    for k in range(n_animals):
        for _ in range(3):
            start = int(rng.integers(0, max(1, n_frames - 20)))
            xy[start : start + int(rng.integers(2, 12)), k, :] = np.nan

    # Identification confidence: high, dipping where animals are close.
    id_probabilities = np.full((n_frames, n_animals), 0.98)
    for t in range(n_frames):
        for k in range(n_animals):
            others = np.delete(np.arange(n_animals), k)
            distances = np.linalg.norm(xy[t, others] - xy[t, k], axis=1)
            if np.nanmin(distances, initial=np.inf) < 60.0:
                id_probabilities[t, k] = float(rng.uniform(0.55, 0.85))

    return xy, id_probabilities


def _arena_polygon(n_vertices: int = 48) -> str:
    """The circular arena as the vertex list idtracker.ai would store."""
    angles = np.linspace(0.0, 2 * np.pi, n_vertices, endpoint=False)
    # float() before round(): round() on a numpy scalar returns a numpy
    # scalar, and json.dumps then writes "np.int64(500)" into the ROI string,
    # which the reader's polygon parser rejects.
    vertices = [
        [round(float(ARENA_CENTRE[0] + ARENA_RADIUS * np.cos(a))),
         round(float(ARENA_CENTRE[1] + ARENA_RADIUS * np.sin(a)))]
        for a in angles
    ]
    return str(vertices)


def write_session(folder: Path, xy: np.ndarray, id_probabilities: np.ndarray) -> None:
    """Write the CSV-bundle session layout idtracker.ai produces."""
    n_frames, n_animals, _ = xy.shape
    traj_dir = folder / "trajectories" / "trajectories_csv"
    traj_dir.mkdir(parents=True, exist_ok=True)

    header = "frame," + ",".join(f"x{k + 1},y{k + 1}" for k in range(n_animals))
    rows = [header]
    for t in range(n_frames):
        values = ",".join(
            f"{xy[t, k, 0]:.3f},{xy[t, k, 1]:.3f}" for k in range(n_animals)
        )
        rows.append(f"{t},{values}")
    (traj_dir / "trajectories.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    prob_header = "frame," + ",".join(f"prob{k + 1}" for k in range(n_animals))
    prob_rows = [prob_header]
    for t in range(n_frames):
        prob_rows.append(
            f"{t}," + ",".join(f"{id_probabilities[t, k]:.4f}" for k in range(n_animals))
        )
    (traj_dir / "id_probabilities.csv").write_text(
        "\n".join(prob_rows) + "\n", encoding="utf-8"
    )

    # attributes.json is the trajectory *payload*, and the reader takes
    # length_unit and identities_labels from there rather than from
    # session.json -- so a session with them only in session.json imports
    # as uncalibrated and unlabelled.
    (traj_dir / "attributes.json").write_text(
        json.dumps(
            {
                "frames_per_second": FPS,
                "body_length": BODY_LENGTH_PX,
                "number_of_animals": n_animals,
                "length_unit": PX_PER_CM,
                "identities_labels": [f"fish_{k + 1}" for k in range(n_animals)],
                "version": "6.0.14",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    (folder / "session.json").write_text(
        json.dumps(
            {
                "frames_per_second": FPS,
                "number_of_animals": n_animals,
                "width": 1000,
                "height": 1000,
                "number_of_frames": n_frames,
                "length_unit": PX_PER_CM,
                "track_wo_identities": False,
                "identities_labels": [f"fish_{k + 1}" for k in range(n_animals)],
                "version": "6.0.14",
                # idtracker.ai records every ROI as a polygon string, even
                # a round arena -- the Validator writes the vertices it
                # sampled, not a centre and radius.
                "roi_list": [f"+ Polygon {_arena_polygon()}"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--minutes", type=float, default=2.0, help="session length (default: 2)"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent / "tiny_session",
        help="destination session folder",
    )
    args = parser.parse_args()

    n_frames = int(args.minutes * 60 * FPS)
    xy, id_probabilities = simulate(n_frames)
    write_session(args.out, xy, id_probabilities)

    coverage = 100 * float(np.mean(~np.isnan(xy[:, :, 0])))
    print(f"wrote {args.out}")
    print(f"  {n_frames} frames, {xy.shape[1]} animals, {args.minutes:g} min @ {FPS:g} fps")
    print(f"  {coverage:.1f}% coverage (deliberate dropouts)")


if __name__ == "__main__":
    main()
