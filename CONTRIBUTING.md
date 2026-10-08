# Contributing to Track2Data

Thank you for your interest in contributing! This document covers the dev setup, workflow, and conventions for the project.

## 1. Dev setup

```bash
git clone <repo-url> track2data
cd track2data
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
pip install -e ".[dev]"
```

Python 3.11+ is required (see `pyproject.toml`).

### Git hooks

Enable the repo's hooks once per clone:

```bash
git config core.hooksPath .githooks
```

This turns on a `pre-commit` hook that runs [`actionlint`](https://github.com/rhysd/actionlint) over `.github/workflows/` whenever a commit touches a workflow file. A malformed workflow is otherwise only discoverable by pushing it and letting a run die at parse time -- and failed runs burn Actions minutes (metered on private repositories). actionlint also type-checks `${{ }}` expressions, including the `fromJSON` matrix selector in `ci.yml`, which a plain YAML parse accepts happily.

Install actionlint itself:

```bash
# Windows
winget install --id rhysd.actionlint --exact
# macOS
brew install actionlint
# Any platform with a Go toolchain
go install github.com/rhysd/actionlint/cmd/actionlint@latest
```

The hook degrades to a warning if actionlint isn't installed, so it never blocks a contributor who hasn't set it up. Bypass it for a single commit with `git commit --no-verify`.

## 2. Running tests

```bash
# All non-r_parity tests (default CI gate)
pytest tests/ -m "not r_parity"

# Synthetic-fixture R-parity tests (CI gate)
pytest tests/test_r_parity/ -m "r_parity and not r_parity_local"

# Local-only R-parity (requires embargoed fixture source; see §6)
pytest tests/test_r_parity/ -m r_parity_local

# Coverage
pytest --cov=track2data --cov-report=term --cov-fail-under=80
```

The coverage gate is 80% (per `docs/TECHNICAL_SPEC.md` §11 and `pyproject.toml`'s `[tool.coverage.report]`). Actual coverage sits well above this floor in practice; treat 80% as a hard minimum, not a target.

## 3. Test-Driven Development

This project follows TDD strictly. The workflow is:

1. **RED** — write a failing test that captures the desired behaviour
2. Run the test and confirm it fails for the **expected reason** (not a typo)
3. **GREEN** — write the minimal production code that makes the test pass
4. Run the test and confirm it passes; confirm other tests still pass
5. **REFACTOR** — clean up while staying green

Never write production code without a failing test first. If you find yourself wanting to "just add a quick fix," write the regression test for it first.

## 4. Branch & PR policy

- `main` is protected. All changes go through pull requests: direct
  pushes, force-pushes and branch deletion are all rejected, and the
  `CI passed` status check must be green before a PR can merge.
- `CI passed` is the aggregate job at the end of
  `.github/workflows/ci.yml`; it fails if any of `lint`, `test` or
  `r_parity` did. It is the *only* required check, deliberately — the
  matrix job names carry the OS and Python version, so requiring them
  directly would mean re-editing the repository settings every time the
  matrix changes.
- No approving review is required, since the project currently has a
  single maintainer. Add a review requirement when a second regular
  contributor appears.
- Administrators are not subject to these rules, so a maintainer can
  still push a hotfix directly if CI itself is broken. Treat that as an
  escape hatch, not a shortcut.
- Feature branches: `feat/<short-name>` (e.g. `feat/savgol-smoother`)
- Bug fixes: `fix/<short-name>`
- Docs-only: `docs/<short-name>`
- Refactors: `refactor/<short-name>`

Each PR should:
- Have a clear title (under 70 characters) describing the **what**
- Include a description with **why** and a **test plan**
- Pass all CI gates (lint, unit tests, r_parity)
- Stay focused — one logical change per PR

## 5. Code style

```bash
# Lint
ruff check .

# Auto-format (if applicable)
ruff format .
```

- Line length: 100 characters
- Type hints required on all public APIs
- `mypy` is advisory for now; will be a hard gate post-v1.0
- Prefer Pydantic models for cross-module data; avoid ad-hoc dicts
- Pure-Python engine (no R at runtime, no GPU, no telemetry)

## 6. R-parity fixture handling

The reference R pipeline lives outside this repository, on the maintainer's machine; ask a maintainer for its location. **The output data from that pipeline is currently pre-publication embargoed and MUST NOT be committed to git.**

For maintainers with disk access:
- Local fixture directory: `tests/fixtures/r_outputs/from_choice_pipeline/`
- This directory is `.gitignore`'d except for its `README.md`
- Populate it locally to enable the `r_parity_local` test gate:
  ```bash
  pytest -m r_parity_local
  ```
- See `tests/fixtures/r_outputs/from_choice_pipeline/README.md` for the embargo-lift checklist + regeneration instructions

For other contributors: the synthetic `tiny_v5` fixture (in `tests/conftest.py`) plus the committed `golden_reader_tiny_v5.csv` are sufficient for the standard `r_parity` gate.

## 7. Documentation

Every change to a metric, error code, or user-visible message must update the corresponding spec:
- New metric → add a `#### <ID> — <name>` section to `docs/METRICS_SPEC.md` §4
- New error code → add a row to `docs/USER_WORKFLOW.md` §6
- New UI screen → add a section to `docs/dev/UI_DESIGN.md` §6

The spec is the contract; code that diverges from spec is a bug.

### Adding a reader (a new tracking software)

The foundation is in `track2data/readers/` and designed in `docs/tracker-formats/`.
A reader for a new tracker is a `SessionReader` subclass; the checklist:

1. **Tests first, on real files where the format is a container.** Add the fixture to
   `tests/real_samples/fixtures_manifest.json` (URL, sha256, licence, attribution) and
   flip that tracker's contract cases from XFAIL to PASS. A text layout documented well
   enough may ship with `verification = "synthetic_only"`; HDF5, MAT, NPZ and SQLite
   need a real sample (DECISIONS D-029).
2. **Declare it honestly.** `name` is saved in project files, so it is frozen once
   released. Set `display_name`, `verification`, `coordinate_frame`,
   `provides_body_length` and `provides_identification_quality` for what the reader
   really supplies, and `parameters` for everything the files do not record (frame
   rate, frame size, which keypoint). A required option that is missing must raise
   `READER_OPTION_MISSING`, never fall back to a default (D-028).
3. **`discover(index, peek)` is a pure function of a `ScanIndex`.** It may read headers
   through `peek` and nothing else: no unpickling, no writes, no file opened by
   other means (D-027). Report HIGH only with a structural marker and no rival, and
   make sure the reader's fixtures give **zero** HIGH on every other tracker's.
4. **`read(path, *, options)` never modifies the input folder** (FR-IMP-5), takes the
   session folder or its primary file, and raises coded errors that carry a
   `remediation`. Declare `accepts_allow_pickle` only if it can load code from a file.
5. **Register it** by importing it in `readers/__init__.py` (built-in) or through the
   `track2data.readers` entry point (plug-in).
6. **Document it:** a reader card in `docs/tracker-formats/README.md`, new error codes
   in `docs/USER_WORKFLOW.md` §6, a `CHANGELOG.md` entry.

A reader of **pose** output (several keypoints per animal) should not reinvent the shared parts;
`track2data/readers/assemble.py` has them. `reduce_keypoints` picks the one keypoint that becomes
`raw_xy` (the one the user named, else the one seen most often after the likelihood cutoff; never
a centroid), `build_keypoints` keeps the whole skeleton beside it (`Session.keypoints`, stored
only), `to_nan` maps infinity and format sentinels to NaN, and `assemble_session` builds the
`Session` after checking it, because the model itself checks nothing. Never put a keypoint
likelihood in `id_probabilities`: that means identity confidence and feeds the identity metrics.

### Metric references

Every specific, findable work a metric cites lives in exactly one place: `track2data/metrics/references.py`,
as a module-level `Reference` constant (`CACHAT_2010`, `ROMERO_FERRERO_2019`, ...). A metric class points
`documentation.primary_reference` at one of these (which fills `citation`/`citation_doi` automatically) and,
optionally, `documentation.supporting_references` at a list of more. Two metrics citing the same work import
the *same* `Reference` object, so their citation text is byte-identical by construction — never retype a
citation string into a second metric class, even if it looks like the same text. A metric with no specific
originating work still sets `citation` directly, as free text ("Standard kinematics; no single originating
work") — inventing a `Reference` for a generic convention would misrepresent it as having one paper behind it.

Adding a metric, or changing any metric's `citation` / `citation_doi` / `primary_reference` /
`supporting_references`, also means regenerating the published reference list and bibliography:

```bash
python scripts/generate_metric_references.py
```

Run this from the full dev environment (`pip install -e ".[dev]"`). The registry loads each metric
module optionally, so on a venv missing `scipy` or `shapely` it would otherwise hold only a subset
of the metrics and the regenerated CSV would quietly lose every row from the module that failed to
import. The script refuses to write in that case and names the missing module.

Commit the resulting `docs/METRIC_REFERENCES.csv` (now with a `supporting_references` column) and
`docs/references.bib` with your change. `tests/test_metric_references_consistency.py` fails otherwise
— it also checks that every metric has a citation, that each DOI is a bare `10.xxxx/...` (not a URL),
that the same DOI is never attached to metrics whose citation texts differ, that every `Reference` a
metric uses is the canonical object from `references.py` (not a free-floating duplicate with the same
key), and that `METRICS_SPEC.md`'s inline **Reference** / **Supporting references** rows match the code.

`Metric.documentation` in the code is the single source of truth. Never hand-edit the CSV or the
`.bib`, and never edit a spec **Reference** / **Supporting references** row without making the same
change in the metric class.

When you add or change a `Reference`, confirm its DOI really points at the work you named:

```bash
pytest tests/test_references_resolve.py -m network
```

That asks Crossref what each DOI actually resolves to and fails if the first-author surname or the
year disagrees with the bibliography. It is marked `network` and excluded from CI — an outage at
Crossref is not a defect in this repository, and thirty-five requests per matrix cell on every push
would be impolite to a free public API — so it only runs when you run it. The same file's offline
guards (bare-DOI shape, unique keys, no DOI shared by two different works) are unmarked and do run
in CI. Note that no automated check can tell you a real paper by the right author actually
*supports* the metric; that judgement is still yours.

A citation must name a real, findable work. If no specific work applies, say so plainly
("Standard kinematics; no single originating work") and leave `citation_doi=None` — an honest
generic reference is correct, an invented DOI is not.

## 8. Commit message style

Conventional Commits are suggested but not strictly enforced. Examples:

```
feat(metrics): add IL-6 acceleration metric
fix(readers): handle pickled trajectories.npy from idtracker.ai 6.0.13
docs: clarify body-length calibration precedence
refactor(preprocess): extract kinematics into separate module
```

## 9. Reporting issues

Open a GitHub issue with:
- What you expected to happen
- What actually happened
- A minimal reproducible example (a session folder + project.t2d.json is ideal)
- Your OS, Python version, and `pip list` output

Security issues should be reported privately to the maintainer (see `CODE_OF_CONDUCT.md` for contact).

## 10. Repository layout oddities

Two directories are not product source and are easy to mistake for it:

**`.claude/skills/`** — a Claude Code *skill* (`run-track2data`) that drives
the GUI and CLI for agent-assisted development: launching the app, taking
screenshots of a wizard screen, reproducing a UI bug, invoking the pipeline
headlessly. It carries a ruff `ANN` exemption in `pyproject.toml` because it
is tooling, not public API.

It has to live at `.claude/skills/` — that is where Claude Code discovers
skills, so relocating it under `tools/` would simply stop it working. Delete
it if you do not use Claude Code; nothing in the package imports it.

**`scripts/extract_bboxes.py`** — an unmaintained utility used by an adjacent
pipeline. Nothing in the package imports it and no test covers it. It has
four confirmed defects catalogued in
[`docs/dev/EXTRACT_BBOXES_FIX.md`](docs/dev/EXTRACT_BBOXES_FIX.md), none of
them applied to this copy, and it loads a pickle with no consent gate. Prefer
`track2data/readers/idtrackerai/blobs.py`, which does the same job with a
restricted unpickler that never executes idtracker.ai code. See issue #80.

---

## 11. Roadmap

See `docs/dev/ROADMAP.md` for the phased M1–M5 build plan. New contributors are welcome to pick up any unblocked item — open an issue first so we can coordinate.

---

Thank you for contributing! By participating in this project, you agree to abide by the `CODE_OF_CONDUCT.md`.

## User guide screenshots

`docs/guide/USER_GUIDE.md` is the single-document user guide, with screenshots in `docs/guide/images/`. When you change how a screen looks, regenerate
them and commit the images:

```bash
python scripts/generate_guide_screenshots.py
```

It drives the real app offscreen against a synthetic demo session. `tests/test_docs/test_guide.py`
fails if a guide section, link or image goes missing.

After editing the guide or its screenshots, rebuild the PDF (needs `pandoc`, Chromium/Chrome and
`pypdf`) and commit it:

```bash
python scripts/build_user_guide.py
```
