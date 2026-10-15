# Interoperability

Where Track2Data sits in the ecosystem, and how its output maps onto the
other tools a movement-analysis pipeline is likely to include.

## Where the boundary is

```
   video ──► tracking / pose ──► TRACK2DATA ──► statistics
             idtracker.ai                       R: lme4, glmmTMB
             DeepLabCut                         Python: statsmodels, scipy
             SLEAP                              your model, your inference
             TRex
```

Track2Data does **not** track, and does **not** do statistics. Both
exclusions are deliberate:

- **No tracking or pose estimation.** idtracker.ai already solves identity
  preservation across crossings, and does it with a trained CNN and years of
  validation behind it. Reimplementing that badly would be the worst
  possible contribution.
- **No statistics.** The right model depends on the design — nested,
  repeated-measures, between-subject, longitudinal — and a tool that guesses
  produces a p-value the user did not choose and cannot defend. Track2Data
  produces the dataset and the provenance record; the model is yours.

What it does own is the part between: turning trajectories into cited,
unit-documented, quality-annotated behavioural measures, and recording
enough about how that happened for someone else to check it.

## Reading Track2Data output elsewhere

`metrics_long.csv` is deliberately in tidy/long form, so it needs no
adapter:

```r
long <- readr::read_csv("out/session_x/metrics_long.csv")
book <- readr::read_csv("out/codebook.csv")
dplyr::left_join(long, dplyr::select(book, column, unit, doi), by = "column")
```

```python
long = pd.read_csv("out/session_x/metrics_long.csv")
book = pd.read_csv("out/codebook.csv")
long.merge(book[["column", "unit", "doi"]].drop_duplicates(), on="column")
```

`master_fish_by_frame.csv` is the per-frame table, in the shape most
trajectory libraries expect: one row per (frame, individual) with `x_px`,
`y_px`, `time_s`, and reconstruction flags.

## Using the `movement` package

[`movement`](https://movement.neuroinformatics.dev/) (Neuroinformatics Unit,
UCL) is an xarray-based library for animal-movement data, with plotting,
filtering and kinematic utilities that Track2Data does not attempt. Track2Data
hands it a preprocessed session as an `xarray.Dataset` in `movement`'s layout.
Install the extra first: `pip install track2data[xarray]`.

```python
from track2data.api import Engine
from track2data.core.manifest import read
from track2data.interop.movement import to_movement_dataset

engine = Engine(read("project.t2d.json"))
psess = engine.preprocess(engine.import_session("session_folder"))
ds = to_movement_dataset(psess)
```

### The mapping

`position` has dimensions `(time, individuals, keypoints, space)`.

| `movement` | Track2Data | Note |
|---|---|---|
| `position` | `PreprocessedSession.xy` (plus `z` for a native 3-D session) | A length-1 `keypoints` axis is added |
| `time` | the session's timeline divided by `fps` | True video time, so a session tracked in separate intervals keeps its gaps |
| `individuals` | `Session.identities_labels`, else `0..n-1` | |
| `keypoints` | the keypoint that stands for the animal, else `"centroid"` | The rest of a skeleton is not exported |
| `space` | `["x", "y"]`, or `["x", "y", "z"]` for a native 3-D session | |
| `identity_confidence` | `Session.id_probabilities` | A separate variable, **not** `confidence` (see below); absent when the tracker gave none |
| attrs | `fps`, `source_software`, `reader_verification`, `length_unit`, `px_per_cm` | `length_unit` is the unit of `position` (`px`, or the file's unit for a native 3-D session) |

The single NaN row that stands for an unfilled gap between tracking intervals
is dropped; pass `include_separator_rows=True` to keep it. Rows for unobserved
video stay as NaN.

### Two things that do not map cleanly

**`confidence` means something different.** In `movement` it is a pose
estimator's per-keypoint confidence: how sure the network is about *where*
the body part is. idtracker.ai's `id_probabilities` is how sure it is about
*which animal* this is, so the position may be exact while the identity is a
coin flip. Writing one into the other's slot would invite a filter on the wrong
quantity, which is why it is named `identity_confidence`.

**Zones and calibration have no home in the pose schema.** `main_zone`,
`sec_zone` and the body-length scale stay in Track2Data; only `px_per_cm`
rides along as an attribute.

| Target | Status | Notes |
|---|---|---|
| CSV (long and wide) | ✅ shipped | `csv_long`, `csv_wide` |
| Excel | ✅ shipped | `excel` exporter, needs `openpyxl` |
| Feather / Arrow | ✅ shipped | `feather` exporter, needs `pyarrow` |
| `movement` xarray | ✅ shipped | `track2data.interop.movement.to_movement_dataset`, needs `xarray` |
| DeepLabCut CSV input (also Lightning Pose, EKS) | ✅ supported | One session per prediction file; the frame rate and frame size are options you give (the file records neither); one keypoint stands for the animal and the whole skeleton is stored beside it. See `docs/tracker-formats/README.md`. |
| SLEAP analysis HDF5 input | ✅ supported | In SLEAP choose *File > Export Analysis HDF5*. One session per file; the frame rate and frame size are options you give; one skeleton node stands for the animal and the whole skeleton is stored beside it. `.slp` project files are not read. See `docs/tracker-formats/README.md`. |
| Ctrax raw `.mat` input | ✅ supported | The file Ctrax's *Save Tracks as Matlab File* writes. Frame size is an option you give; the frame rate comes from the file. Ctrax track ids are fragments, so a session is identity-free and one slot per id (`top_n` keeps the longest). See `docs/tracker-formats/README.md`. |
| `trx.mat` input (Ctrax / FlyTracker / JAABA) | 🧪 synthetic only | A classic (v5/v7) MATLAB file holding a `trx` struct, built from the documented layout with no real sample pinned yet. Frame size is an option; `fps` is read from the file. `pxpermm` (pixels per mm) becomes the session scale for Session calibration, pending the usual unit confirmation; a value of exactly 1 is ignored. v7.3 files are not read. |
| DeepLabCut `.h5` input | 🕒 planned | Waiting on the decoder decision in the reader rollout (`docs/tracker-formats/`). Until then export DeepLabCut as CSV. A reader plug-in is also possible — see the `track2data.readers` entry point in `CONTRIBUTING.md`. |
| NWB | ❌ not planned | Would be worth revisiting if the behavioural-NWB extensions stabilise. |

Writing a reader for another tracker does not require changing Track2Data:
implement `SessionReader` and register a `track2data.readers` entry point.
See `docs/ENGINE_DESIGN.md` for the plug-in surface, and
`SessionReader.accepts_allow_pickle` if your format executes code on load.
