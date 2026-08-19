# Track2Data

Open-source desktop application that turns `idtracker.ai` output folders into analysis-ready behavioural datasets.

See [PRD.md](PRD.md) for the full product requirements. Design and workflow docs live in [docs/](docs/):

- [`docs/ROADMAP.md`](docs/ROADMAP.md) — phased M1–M5 implementation plan, module build order, and exit criteria.
- [`docs/TECHNICAL_SPEC.md`](docs/TECHNICAL_SPEC.md) — **read first.** System-level technical contract: tech stack, architecture, project file format, build/packaging, testing pyramid, plug-in compatibility policy.
- [`docs/USER_WORKFLOW.md`](docs/USER_WORKFLOW.md) — the end-to-end user journey through the wizard, wireframes, validation messages, and save/resume logic.
- [`docs/UI_DESIGN.md`](docs/UI_DESIGN.md) — PySide6 wizard architecture and engine bindings.
- [`docs/ENGINE_DESIGN.md`](docs/ENGINE_DESIGN.md) — pure-Python `track2data` engine: layout, models, plug-in surface.
- [`docs/IDTRACKERAI_FORMAT_ANALYSIS.md`](docs/IDTRACKERAI_FORMAT_ANALYSIS.md) — gap analysis of the current reader against the official idtracker.ai 6.0.14 docs and a 70-session real-data corpus; cross-version normalisation strategy.
- [`docs/METRICS_SPEC.md`](docs/METRICS_SPEC.md) — canonical, implementation-ready specification for every behavioural metric (formulas, inputs, outputs, units, citations) plus the UI info-button architecture.

Contributing: see [`CONTRIBUTING.md`](CONTRIBUTING.md) for dev setup, TDD workflow, branch policy, and how to run tests.

## Installation

**Engine only** (CLI + headless processing, no PySide6):
```bash
pip install -e "."
track2data --help
```

**Desktop GUI** (adds PySide6):
```bash
pip install -e ".[ui]"
track2data-gui
# or: python -m app.main
```

## Development setup

```bash
pip install -e ".[dev]"
pytest                                  # all tests (engine + UI smoke)
pytest tests/ -m "not r_parity" -v     # skip R-parity (no fixture data needed)
pytest tests/test_app_smoke.py -v      # Phase 1 smoke tests only
ruff check .                            # lint
```

## Running the app (Phase 1 shell)

```bash
# After pip install -e ".[ui]":
track2data-gui

# Or directly:
python -m app.main
```

The Phase 1 shell opens a 7-stage wizard with placeholder screens.
Full functionality is implemented in subsequent phases.
