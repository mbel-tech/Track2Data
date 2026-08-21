# Fixing `extract_bboxes.py`

This is a standalone guide for correcting `extract_bboxes.py` — the script
at this repo's root that extracts per-(frame, identity) bounding-box body
lengths from an idtracker.ai session's `preprocessing/list_of_blobs.pickle`.
It is written to be applied to **a copy of the script wherever you actually
run it** (a separate pipeline), not just this repository. Every claim below
is either quoted from the official idtracker.ai 6.0.15a0 API reference or
measured directly against a real session in a 70-session tracked corpus —
none of it is inferred from reading the script alone.

Track2Data itself does **not** wire this script's output into its
calibration path (see the format-alignment plan, Fase 7) — the bias
documented below is why. This guide exists so the script can still be fixed
for use elsewhere.

## 1. Summary

The script currently overestimates body length by **+27.8%** on a real
session, with a **1.75×** spread between individual medians of the same
species in the same arena — an error large enough to fabricate group
differences in any study comparing segmentation quality across treatment
arms. It also silently produces **zero rows** on any machine without
`idtrackerai` installed, despite advertising a pickle fallback. After
applying the fixes below, the script's own per-identity median reconciles
with idtracker.ai's own `median_body_length` to within about 1%.

## 2. Defects that make the script silently produce nothing

Fix these first — without them, nothing downstream can be verified, because
the script exits 0 having written zero usable rows.

| # | Line | Problem | Fix |
|---|---|---|---|
| B1 | `extract_bboxes.py:47` | Reads `blob.contours`. The real attribute is `blob.contour` (singular) — `contour: ndarray` — "The coordinates of the contour defining self with shape [n_points, 2]" (`blob_idtrackerai.md:13`). `contours` does not exist under any idtracker.ai version referenced by the docs. | Rename `blob.contours` → `blob.contour`, and stop calling `np.vstack` on it — `blob.contour` is already a single `(n_points, 2)` array, not a list of contours. |
| B2 | `extract_bboxes.py:39` | `blob.extension` is declared `property extension: float` — "Extension measured as the length of the diagonal of the bounding box" (`blob_idtrackerai.md:99`). It is a **computed property**, not pickled state. On any environment where the blobs were loaded via a plain `pickle.load` fallback (see B3) rather than through a live `idtrackerai` installation, this attribute simply does not exist, and `hasattr(blob, "extension")` is `False`. | Compute it directly from `blob.contour` instead of relying on the property (see §4 for the exact formula) so the script works identically whether or not `idtrackerai` is importable. |
| B3 | `extract_bboxes.py:11-14, 24-31` | The `try: import idtrackerai / except ImportError` block, combined with `ListOfBlobs.load(path)` failing and falling through to a bare `pickle.load(f)`, is **not actually a fallback**. `list_of_blobs.pickle` is written with `STACK_GLOBAL` opcodes referencing `idtrackerai.list_of_blobs.ListOfBlobs` and `idtrackerai.blob.Blob` (verified by inspecting the file's raw bytes). A plain `pickle.load` on a machine without `idtrackerai` installed raises `ModuleNotFoundError: No module named 'idtrackerai'` — the exact same failure the `try/except ImportError` at the top of the file was meant to route around. | Replace the bare `pickle.load(f)` fallback with a `pickle.Unpickler` subclass that overrides `find_class` to return a lightweight stand-in class for any `idtrackerai.*` name (see §5 for a working implementation and the security note that goes with it). This loads the real pickled **state** (everything listed in §3) without ever importing or executing idtracker.ai code. |
| B4 | `extract_bboxes.py:112` | `lob.number_of_frames` is a **property** on the live `ListOfBlobs` class, not a pickled attribute. Under the stub-loading fix in B3, accessing it raises `AttributeError`, which is caught by the surrounding `except Exception as e` and reported as `"Error loading blobs"` — the whole session then gets `status: "error"` with **zero rows written**, even though the blob data loaded fine. | Use `len(blobs_in_video)` instead — `blobs_in_video` (the pickled list-of-lists-of-`Blob`) is real state and its outer length is exactly `number_of_frames`. |

## 3. What is actually inside the pickle (verified empirically)

The official docs do not publish a field-by-field list of what
`__getstate__()` serialises — `blob_idtrackerai.md` documents the method
with exactly four words, "Helper for pickle." (`blob_idtrackerai.md`, the
`__getstate__` entry). The complete, real set of keys on a `Blob` loaded
from a real `list_of_blobs.pickle`, confirmed across many sampled blobs, is:

```
contour, frame_number, bbox_img_id, episode, id_image_index,
is_an_individual, seems_like_individual, used_for_training_crossings,
forced_crossing, added_by_user, identity, identity_certainty,
fragment_identifier, identity_corrected_solving_jumps,
identities_corrected_closing_gaps, user_generated_identities,
user_generated_centroids, interpolated_centroids, next, previous
```

**Not present** in the pickle (confirmed by a full byte-level scan of a real
file): `area`, `extension`, `bbox_corners`, `convexHull`, `centroid`,
`exclusive_roi`, `was_a_crossing`. Every one of these is a
`functools.cached_property` on the live class — computed from `contour` on
first access, never stored. Any script that reads them via `getattr(blob,
"area", None)` (as this script does at line 170) will silently get `None`
under stub-loading, not an error — which is a second, quieter version of
the B2 problem: it degrades instead of crashing, so it is easy to miss.

**Also confirmed empty on every sampled blob:** `next` and `previous` are
both `()` — the overlapping-frame graph is stripped before saving. Do not
build anything on `blob.next`/`blob.previous`, `has_multiple_next`,
`has_a_next_crossing`, or similar — none of it survives the pickle, with or
without `idtrackerai` installed.

## 4. Defects that produce wrong numbers

This is the core of the fix.

### N1 — Wrong population for the body-length median (+27.8% bias)

The script's body-length figure is built from every blob where
`is_an_individual` is true (line 194: `is_individual is True`). idtracker.ai
defines its own `median_body_length` differently.
`session_idtrackerai.md` documents it as:

> `median_body_length: float` — median of the diagonals of individual blob's
> bounding boxes

and the qualifying condition for "individual" here is narrower than
`is_an_individual` alone —
`blob_idtrackerai.md:21` documents `seems_like_individual` as:

> `seems_like_individual: bool` — Unicity condition or not huge area

Measured on a real session (`session.json:median_body_length` =
`trajectories.npy['body_length']` = **150.153**, the two are byte-identical
in the tracker's own output):

| Population | n blobs | Median bbox diagonal |
|---|---|---|
| `is_an_individual` (what the script currently uses) | 34,571 | 184.11 |
| unicity frames (exactly `n_animals` blobs in the frame) ∧ `seems_like_individual` | 6,746 | **150.66** |
| idtracker.ai's own `median_body_length` | — | **150.153** |

The script's actual CSV output on that session has `median(body_length_px)
= 191.86` — **+27.8%** high — with per-identity medians of `{1: 230.8, 2:
206.5, 3: 132.1, 4: 152.8}`, a 1.75× spread between four fish in the same
arena that should be roughly the same size.

**Fix:** change the per-frame filter (around lines 129–190) to only build
candidates from blobs where **both** `seems_like_individual` is true **and**
the frame has exactly `n_animals` blobs (`len(blobs_in_frame) ==
n_animals`), not merely `is_an_individual`. `n_animals` is available from
`attrs.json`'s `number_of_animals` key, or from
`len(session.json["identities_labels"])`.

### N2 — `blob.final_identities` does not exist in the 6.0.15 API

`extract_bboxes.py:136`:

```python
if hasattr(blob, "final_identities") and blob.final_identities:
    identities = blob.final_identities
elif hasattr(blob, "identity") and blob.identity is not None:
    identities = [blob.identity]
```

The real accessors, per `blob_idtrackerai.md:231` and `:263`, are:

> `property assigned_identities: list[None] | list[int] | list[int | None]` —
> Identities assigned to the blob during the tracking process

> `property all_final_identities: list` — Identities of the blob after the
> tracking process **and after potential modifications by the users during
> the validation procedure**.

`final_identities` appears nowhere in the reference. It is very likely an
alias that happened to exist on the specific idtracker.ai build the script
was originally written against, and it is already gone from 6.0.15.

**Concrete failure mode, measured on real data.** On frame 5 of a real
session:

| Source | Value |
|---|---|
| `blob.identity` (raw, pre-validation) | `4` |
| `blob.user_generated_identities` | `[-1, 1]` |
| The session's own `trajectories.npy` at that frame/position | identity **1** |
| The corresponding row the script itself wrote | `identity=1` |

The true, user-corrected identity is **1**; the raw pre-validation identity
is **4**. Today's `hasattr(blob, "final_identities")` branch happens to
resolve correctly only because the specific idtracker.ai build in use still
carries that alias. The moment it does not (it already does not per the
6.0.15 reference), the `elif` silently falls through to `blob.identity` —
the pre-validation value — and every row for that blob gets written under
the wrong identity, with no error, no warning, and no change in row count.
One real session in the corpus has over 40,000 blobs carrying user
corrections; this is not an edge case.

**Fix:** use `blob.all_final_identities` as the primary source (it is
exactly the "after validation" value the field name in this script,
`identity`, implies it should be). Keep a fallback to `blob.identity`, but
make it **loud**: log or count how often the fallback fires, and surface
that count in the summary JSON, so a silent behaviour change is at least
visible in aggregate.

### N3 — A crossing blob with one identity gets stamped "individual"

`extract_bboxes.py:164-165`:

```python
if is_ind is None:
    is_ind = (len(valid_identities) == 1)
```

Under stub-loading (B3), `blob.is_a_crossing` is unavailable (it's a
property, not state) so `is_ind` is often `None` here — and a crossing blob
that received exactly one identity through interpolation gets stamped
`is_individual=True`, survives the individual-only filter at line 194, and
has its merged, two-animal bounding box written out as a body length.
Measured: the very first data row of one real session has
`is_an_individual=True`, a 95×348 px bounding box (diagonal 359.5 px)
against a tracker-reported `median_body_length` of 150.15 — a box more than
2× too big.

**Fix:** when the true flag is unavailable, resolving ambiguity toward
**exclusion**, not inclusion — `is_ind = False` when it cannot be determined
some other way, not `len(valid_identities) == 1`. A blob you are not sure is
an individual should not silently become a body-length data point.

### N4 — `area_px` is actually px², and the value used for it doesn't exist

`extract_bboxes.py:170, 182, 227`: the column is named `area_px` and reads
`getattr(blob, "area", None)`. Per `blob_idtrackerai.md:91`:

> `property area: float` — Area of the contour computed with
> `cv2.contourArea()`

Two separate problems: (a) `area` is not in the pickled state (§3) — under
stub-loading this column is `None` on every row, silently; (b)
`cv2.contourArea()` returns **square pixels**, not a linear pixel count, so
a column named `area_px` sitting next to `body_length_px` invites a
downstream user to divide it by `length_unit` (linear conversion) instead
of `length_unit ** 2`.

**Fix:** compute the area from `blob.contour` directly with `cv2.contourArea`
(or a pure-numpy shoelace formula if you want to avoid an OpenCV
dependency), and rename the column `area_px2`.

### N5 — `identity_certainty` is recorded and never used to filter anything

`extract_bboxes.py:169, 182` reads and writes `identity_certainty` but
nothing gates on it. Measured on one real session: **23.35%** of rows have
`identity_certainty < 0.5`, **18.86%** have `< 0.05`, and the very first
data row in the file has `identity_certainty = 0.009445936` — essentially a
coin flip, written into the dataset with no distinguishing flag.

**Fix:** add a configurable minimum-certainty threshold (default something
defensible, e.g. 0.5) and either drop or flag rows below it; report the
threshold used and how many rows it excluded in the summary JSON.

### N6 — `identity_stats` in the summary is silently empty on every real session

`extract_bboxes.py:241-256` aggregates `body_length_cm`, which is `None`
whenever `length_unit` is `None` (line 157-158). `length_unit` is `null` in
every real `attributes.json` sampled in this corpus (70/70). The result is
that every `_bboxes_summary.json`'s `identity_stats` reports `{"n_frames":
0}` for every identity — even though the corresponding CSV has tens of
thousands of rows. A QC summary that silently reports zero data when there
is plenty is worse than no summary at all.

**Fix:** aggregate `body_length_px` (always available when the row was
written at all) and convert to real units only if `length_unit` is present,
rather than aggregating the already-converted (and often absent) column.

## 5. Loading the pickle safely, without `idtrackerai` installed

`list_of_blobs.pickle` pickles custom classes
(`idtrackerai.list_of_blobs.ListOfBlobs`, `idtrackerai.blob.Blob`) via
`STACK_GLOBAL` opcodes. A bare `pickle.load()` therefore requires
`idtrackerai` to be importable, even though `idtracker.ai`'s own docs
describe pickle as one of several interchangeable output formats and
specifically warn (`output_structure_idtrackerai.md`, HDF5/NPY/Pickle
sections, repeated for both NPY and Pickle): "**The pickle module is not
secure**."

A `pickle.Unpickler` subclass that overrides `find_class` to hand back a
lightweight stand-in for any `idtrackerai.*` class name loads the real
pickled state (§3) without ever importing or executing idtracker.ai code —
and, because it never falls through to the real `pickle.Unpickler.find_class`
for unrecognised names, it is **more restrictive** than the script's current
bare `pickle.load()`, not less:

```python
import pickle


class _Stub:
    """Placeholder for any idtrackerai.* class encountered while
    unpickling. __setstate__ deposits the real pickled attributes onto
    this instance; no idtrackerai code ever runs."""

    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state)
        else:
            self.__dict__["_state"] = state


class _SafeUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if module.startswith("idtrackerai"):
            return _Stub
        # Only allow the numpy internals idtracker.ai's own arrays need;
        # refuse everything else outright rather than silently trusting it.
        if module.startswith("numpy"):
            return super().find_class(module, name)
        raise pickle.UnpicklingError(
            f"Refusing to unpickle {module}.{name} (not in the allowlist)."
        )


def load_list_of_blobs_safely(path):
    with open(path, "rb") as f:
        return _SafeUnpickler(f).load()
```

This loaded a real 50 MB `list_of_blobs.pickle` (14,911 frames) in about 1.6
seconds in testing, with `idtrackerai` not installed in the environment.

Use this instead of both the `ListOfBlobs.load(path)` call and the bare
`pickle.load(f)` fallback at `extract_bboxes.py:24-31`. If `idtrackerai` **is**
installed and you want the real class behaviour (methods, not just state),
keep that as the first attempt and fall back to `load_list_of_blobs_safely`
— but make sure the fallback is this stub-loader, not a bare `pickle.load`
that fails identically to the primary path.

## 6. Conventions that are easy to get backwards

- **`extension` uses inclusive bounding-box corners**, not
  `cv2.boundingRect`'s width/height. On a real blob (verified directly:
  contour x spans 1001–1095, y spans 554–901), `cv2.boundingRect` gives
  `w=95, h=348` → diagonal `hypot(95, 348) = 360.734`; the tracker's own
  recorded value for this exact blob is `359.5066063370741`, which is
  exactly `hypot(94, 347)` — i.e. `(right - left)` and `(top - bottom)` on
  **inclusive** corner coordinates, one pixel narrower on each axis than
  `boundingRect`'s convention. If you recompute this from `contour`, use
  `contour.ptp(axis=0)` (peak-to-peak, i.e. `max - min` per axis) rather
  than `cv2.boundingRect`, or your recomputed value will drift about 0.3%
  from the tracker's own and will never quite reconcile — small enough to
  look like a rounding bug you can't find.
- **`bbox_corners` is `(bottom, left, top, right)`**
  (`blob_idtrackerai.md:95`: "A NamedTuple of the bottom, left, top and
  right values of the bounding box"), **not** `(x0, y0, x1, y1)` and not
  OpenCV's `(x, y, w, h)`. Meanwhile `contour` itself is plain `(x, y)`
  pairs — two different conventions on the same object. Since image
  coordinates grow downward, "bottom" is very likely the numerically larger
  row (visually the bottom of the image) — verify against a known blob
  before trusting this axis order in a new computation.
- **`blob.identity` is 1-based** ("From 1 to n_animals" is the convention
  used across the fragment-layer docs for the equivalent field). If you join
  this script's output against anything that uses 0-based identity indices
  (Track2Data's `individual_id`, for instance), you will be off by one.
- Boolean-looking attributes read off a stub-loaded blob can arrive as
  **0-d numpy arrays**, not Python `bool` — wrap them in `bool(...)`
  explicitly rather than relying on truthiness or `is True` checks passing
  automatically.
- `estimated_body_length` is documented as **deprecated since version
  6.0.0** in favour of `extension` (`blob_idtrackerai.md:375`). Don't add a
  code path that tries it first "for compatibility" — that's the old,
  superseded value.
- Filter macOS resource-fork files (`._list_of_blobs.pickle`, 4096 bytes,
  sits right next to the real file on any OneDrive/iCloud-synced corpus)
  before attempting to unpickle anything matching `list_of_blobs*.pickle*`.
- **Which pickle file is authoritative is not always obvious.** Some
  sessions carry a separate `list_of_blobs_validated.pickle` alongside the
  base file — that's the one with the Validator's manual corrections baked
  in. And a base `list_of_blobs.pickle` can itself be re-saved in place by
  the Validator (its mtime will be newer than the rest of the
  `preprocessing/` folder if so). Pick one explicitly, and **write which
  file you used into the summary JSON** — otherwise you can end up silently
  mixing curated and uncurated sessions in the same batch with no way to
  tell afterward which was which.

## 7. Verifying the fix worked

One number is the real acceptance test:

> The script's own per-identity median `body_length_px` must reconcile with
> `session.json → median_body_length` to within roughly 1%.

Before these fixes: **191.86 vs 150.15 — a 27.8% gap.** After applying N1
(the population filter) correctly, the reconciliation on the same session
measured **150.66 vs 150.15 — 0.3%.**

A second, cheap sanity check: per-identity medians for animals of the same
species tracked in the same arena should not differ from each other by
anything close to a factor of 2. Before the fix, one real session produced
`{1: 230.8, 2: 206.5, 3: 132.1, 4: 152.8}` — a 1.75× spread. After the fix,
that spread should shrink to something explainable by genuine size
variation between individuals, not segmentation artefacts.
