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

## Planned: the `movement` package

[`movement`](https://movement.neuroinformatics.dev/) (Neuroinformatics Unit,
UCL) is an xarray-based library for animal-movement data. It is a natural
downstream consumer: it has plotting, filtering and kinematic utilities that
Track2Data does not attempt, and it reads pose data from DeepLabCut, SLEAP
and others.

**Not implemented yet.** The mapping is documented here first so that the
shape of the adapter is agreed before it is written, and so anyone who wants
it in the meantime can do the conversion by hand.

### The mapping

`movement` centres on a `xarray.Dataset` with a `position` DataArray of
dimensions `(time, individuals, keypoints, space)`.

| `movement` | Track2Data | Note |
|---|---|---|
| `position` | `PreprocessedSession.xy`, `(n_frames, n_animals, 2)` | Add a length-1 `keypoints` axis |
| `time` | `frame / fps` | `time_s` in the per-frame table |
| `individuals` | `Session.identities_labels`, else `0..n-1` | Labels come from the Validator when set |
| `keypoints` | a single `"centroid"` | idtracker.ai tracks a centroid, not a skeleton |
| `space` | `["x", "y"]` | Always 2-D |
| `confidence` | `Session.id_probabilities` | Identity confidence, **not** pose confidence — see below |
| `fps` (attr) | `Session.video.fps` | |
| `source_software` (attr) | `"idtracker.ai"` | |

### Two things that do not map cleanly

**`confidence` means something different.** In `movement` it is a pose
estimator's per-keypoint confidence: how sure the network is about *where*
the body part is. idtracker.ai's `id_probabilities` is how sure it is about
*which animal* this is — the position may be exact while the identity is a
coin flip. Writing one into the other's slot would silently invite a filter
on the wrong quantity. Any adapter should carry it as a separately-named
variable, or document the substitution loudly.

**Zones and calibration have no home in the pose schema.** `main_zone`,
`sec_zone`, `px_per_cm` and the body-length scale are Track2Data concepts.
They would ride along as dataset attributes and extra data variables, which
`movement` tolerates but does not interpret.

### If you need it now

```python
import numpy as np
import xarray as xr
from track2data.api import Engine
from track2data.core.manifest import read

engine = Engine(read("project.t2d.json"))
psess = engine.preprocess(engine.import_session("session_folder"))

n_frames, n_animals, _ = psess.xy.shape
labels = psess.session.identities_labels or [str(k) for k in range(n_animals)]

ds = xr.Dataset(
    {
        "position": (
            ("time", "individuals", "keypoints", "space"),
            psess.xy[:, :, np.newaxis, :],
        )
    },
    coords={
        "time": np.arange(n_frames) / psess.fps,
        "individuals": labels,
        "keypoints": ["centroid"],
        "space": ["x", "y"],
    },
    attrs={"fps": psess.fps, "source_software": "idtracker.ai"},
)
```

## Other formats

| Target | Status | Notes |
|---|---|---|
| CSV (long and wide) | ✅ shipped | `csv_long`, `csv_wide` |
| Excel | ✅ shipped | `excel` exporter, needs `openpyxl` |
| Feather / Arrow | ✅ shipped | `feather` exporter, needs `pyarrow` |
| `movement` xarray | 📋 documented above | Not implemented |
| DeepLabCut CSV input (also Lightning Pose, EKS) | ✅ supported | One session per prediction file; the frame rate and frame size are options you give (the file records neither); one keypoint stands for the animal and the whole skeleton is stored beside it. See `docs/tracker-formats/README.md`. |
| DeepLabCut `.h5`, SLEAP input | 🕒 planned | Next in the reader rollout (`docs/tracker-formats/`). Until then export DeepLabCut as CSV, or SLEAP as an analysis file once that reader lands. A reader plug-in is also possible — see the `track2data.readers` entry point in `CONTRIBUTING.md`. |
| NWB | ❌ not planned | Would be worth revisiting if the behavioural-NWB extensions stabilise. |

Writing a reader for another tracker does not require changing Track2Data:
implement `SessionReader` and register a `track2data.readers` entry point.
See `docs/ENGINE_DESIGN.md` for the plug-in surface, and
`SessionReader.accepts_allow_pickle` if your format executes code on load.
