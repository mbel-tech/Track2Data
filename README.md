# Track2Data

**Turn idtracker.ai output folders into analysis-ready behavioural datasets.**

You tracked your animals. idtracker.ai gave you a folder of trajectories.
Track2Data turns that into tables you can put straight into R or Python:
50 behavioural metrics, every one with a citation, in documented units,
with a record of exactly which frames were measured and which were
reconstructed.

It is a desktop application and a Python engine you can drive headlessly for batch or HPC work.

**New here? Start with the [user guide](docs/guide/USER_GUIDE.md)**: a single step-by-step walkthrough of the app with screenshots, also available as a [PDF download](docs/guide/Track2Data_User_Guide.pdf).

> **Status:** v0.1.0, pre-1.0. Usable, and its numbers are tested against
> analytic ground truth and a reference R pipeline — but read the
> [CHANGELOG](CHANGELOG.md) before upgrading, since metric definitions are
> still being corrected.

---

## What it does

```
  idtracker.ai session folder          Track2Data                  your analysis
  ───────────────────────────          ──────────                  ─────────────
   trajectories.npy / .h5      ──►  import  → preprocess    ──►   metrics_long.csv
   session.json                             → calibrate           trial_activity_summary.csv
   list_of_fragments.json                   → define zones        master_fish_by_frame.csv
                                            → choose metrics      codebook.csv
                                            → export              sessions.csv
```

**Individual** — distance travelled, speed, acceleration, tortuosity,
freezing bouts, thigmotaxis, turn rate, home-base use.
**Group** — nearest-neighbour and inter-individual distance, polarisation,
cohesion, convex hull area, milling/swarming state.
**Zone** — occupancy, dwell time, visit counts, transitions, Jacobs' D.
**Diagnostics** — tracking coverage, identity stability, crossing rate,
physical-plausibility violations, and how much of each metric's input was
actually measured rather than interpolated.

Every metric carries a DOI. Nothing is computed without one.

## What it deliberately does not do

Track2Data starts where the tracker stops. It does **not** do pose
estimation or tracking (that is idtracker.ai, DeepLabCut, SLEAP), and it
does **not** do statistics — no models, no p-values, no plots of your
result. It produces the dataset you run those on, and the provenance record
you need to defend it.

## Install

**Pre-built application** — no Python needed. Download for your OS from the
[Releases page](https://github.com/mbel-tech/Track2Data/releases).

Releases are unsigned, so your OS will warn on first run. That is expected:
the free code-signing programme for open-source projects requires a project
to have already published a release, so the first one cannot be signed. See
[`docs/CODE_SIGNING.md`](docs/CODE_SIGNING.md).

- **Windows** — SmartScreen says "Windows protected your PC": **More info** → **Run anyway**.
- **macOS** — Gatekeeper blocks it: right-click `Track2Data.app` → **Open** → **Open**.
  (A plain double-click reports the app as damaged. That is Gatekeeper, not a bad download.)
- **Linux** — `chmod +x Track2Data-x86_64.AppImage`.

Verify your download first — every release ships `SHA256SUMS.txt`:

```bash
sha256sum -c SHA256SUMS.txt
```

**From source:**

```bash
pip install -e ".[ui]"     # desktop app
track2data-gui

pip install -e "."         # engine + CLI only, no PySide6
track2data --help
```

## Quickstart

```bash
track2data new my-study.t2d.json          # scaffold a project
track2data add my-study.t2d.json /path/to/trajectories   # find the sessions, confirm the software
track2data validate my-study.t2d.json     # check it before spending time on a run
track2data run my-study.t2d.json          # import → preprocess → metrics → export
```

Or launch `track2data-gui` and walk the wizard: **Sessions → Calibration →
Zones → Metadata → Metrics → Process → Export**.

**Want to see the output before pointing it at your own data?** There is a
complete two-minute example that runs in about ten seconds:

```bash
cd examples && track2data run example.t2d.json -o out
```

See [`examples/README.md`](examples/README.md) — it also ships starter
analysis scripts for R (`lme4`/`glmmTMB`) and Python (`statsmodels`), and a
short note on the four ways this kind of data is most often mis-analysed.

## What you get out

Every run writes a directory like this:

```
exports/2026-08-30T1408/
├── PROJECT_SUMMARY.md          what ran, what failed, what not to pool
├── sessions.csv                per-session fps, group size, duration, calibration
├── codebook.csv                every column: unit, level, metric, DOI
└── session_trial01/
    ├── metrics_long.csv              one row per value — feed this to lme4/statsmodels
    ├── trial_activity_summary.csv    one row per individual, a column per metric
    ├── group_dynamics_summary.csv
    ├── master_fish_by_frame.csv      per-frame positions and kinematics
    ├── manifest.json                 every parameter, plus input checksums
    └── README.md
```

`metrics_long.csv` is the tidy/long form:

| session_id | individual_id | metric_id | column | value | unit |
|---|---|---|---|---|---|
| trial01 | 0 | IL-1 | path_length_cm | 412.7 | cm |
| trial01 | 0 | IL-2 | mean_speed_cm_s | 3.44 | cm/s |
| trial01 | 1 | IL-1 | path_length_cm | 388.1 | cm |

Join it to `codebook.csv` on `column` for the unit, definition and DOI of
anything in it. **Read the codebook before trusting a column name to imply
its unit** — notably, every `*_pct` column holds a fraction in [0, 1], not a
percentage.

## Reproducibility

The point of the manifest is that someone else can check your numbers. Each
run records the app version, every preprocessing and metric parameter, a hash
of the project configuration, and a SHA-256 of each session's trajectory
file — so "these bytes produced these numbers" is a checkable claim, and a
source folder that changed underneath you is reported rather than silently
used.

To reproduce a dataset, send the `.t2d.json` plus the original session
folders. The reviewer runs:

```bash
track2data run project.t2d.json
```

### How much of this result is the preprocessing?

The question a reviewer will ask. Answer it before they do:

```bash
track2data sensitivity my-study.t2d.json -o sensitivity
```

That recomputes every selected metric across a grid of smoothing windows and
gap-fill limits, and reports how far each column moved — as a coefficient of
variation, so columns in different units are comparable. A value near zero
means the choice barely mattered; a large one means the number is
substantially a statement about the settings rather than the animals.

`sessions.csv` and `PROJECT_SUMMARY.md` say when sessions are **not**
comparable — different frame rates, group sizes, resolutions or calibration
states — because pooling across those without accounting for them produces a
wrong result with nothing to indicate it.

## Requesting a metric

If a measure you need is missing,
[open a metric request](../../issues/new?template=metric_request.yml). The
form asks for the metric's level, its name, and **a DOI** for the paper
defining it. The DOI is required: it becomes that metric's row in the
reference list, and a proposal with no citable source cannot become one.

Existing references are published in
[`docs/METRIC_REFERENCES.csv`](docs/METRIC_REFERENCES.csv) and
[`docs/references.bib`](docs/references.bib), and shown in the app's ⓘ dialog.

## How to cite

Cite the upstream tracker as well as this tool:

> Romero-Ferrero, F., Bergomi, M. G., Hinz, R. C., Heras, F. J. H., &
> de Polavieja, G. G. (2019). idtracker.ai: tracking all individuals in
> small or large collectives of unmarked animals. *Nature Methods*, 16,
> 179–182. https://doi.org/10.1038/s41592-018-0295-5

For Track2Data itself, GitHub's **Cite this repository** button reads
[`CITATION.cff`](CITATION.cff). A per-release DOI via Zenodo is set up but
not yet switched on (see [`docs/dev/RELEASING.md`](docs/dev/RELEASING.md));
until it is, cite the version and commit you ran — both are recorded in
every export's `manifest.json`.

## Documentation

A rendered site is published from these files at
**<https://mbel-tech.github.io/Track2Data/>**, including a browsable
catalogue of all 50 metrics with their formulas, units and DOIs.

**Using it**

- [`docs/guide/`](docs/guide/USER_GUIDE.md) — the user guide (also as a [PDF](docs/guide/Track2Data_User_Guide.pdf)): every screen, with screenshots, plus the output-file reference and troubleshooting
- [`docs/USER_WORKFLOW.md`](docs/USER_WORKFLOW.md) — the wizard, screen by screen
- [`docs/BENCHMARKING.md`](docs/BENCHMARKING.md) — how to time sequential vs parallel runs on your own machine and data
- [`docs/INTEROPERABILITY.md`](docs/INTEROPERABILITY.md) — where Track2Data sits in the ecosystem, and reading its output elsewhere
- [`docs/METRICS_SPEC.md`](docs/METRICS_SPEC.md) — every metric: formula, inputs, units, assumptions, citation
- [`docs/CODE_SIGNING.md`](docs/CODE_SIGNING.md) — why releases are unsigned, and the plan
- [`SECURITY.md`](SECURITY.md) — reporting a vulnerability, and handling untrusted session folders

**Contributing and internals**

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup, TDD workflow, branch policy, adding a metric
- [`docs/TECHNICAL_SPEC.md`](docs/TECHNICAL_SPEC.md) — architecture, project file format, testing strategy
- [`docs/ENGINE_DESIGN.md`](docs/ENGINE_DESIGN.md) — engine layout, models, plug-in surface
- [`docs/IDTRACKERAI_FORMAT_ANALYSIS.md`](docs/IDTRACKERAI_FORMAT_ANALYSIS.md) — the reader vs. the real idtracker.ai formats
- [`docs/dev/`](docs/dev/) — product requirements, roadmap, decision record, UI design

## Development

```bash
pip install -e ".[dev]"
pytest -m "not r_parity and not network"   # the usual run
mypy                                        # engine type check
ruff check .                                # lint
```

## Licence

See [`LICENSE`](LICENSE).
