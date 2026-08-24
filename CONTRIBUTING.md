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

This turns on a `pre-commit` hook that runs [`actionlint`](https://github.com/rhysd/actionlint) over `.github/workflows/` whenever a commit touches a workflow file. A malformed workflow is otherwise only discoverable by pushing it and letting a run die at parse time -- and this repo is private, so those Actions minutes are metered. actionlint also type-checks `${{ }}` expressions, including the `fromJSON` matrix selector in `ci.yml`, which a plain YAML parse accepts happily.

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

- All changes go through pull requests — by convention, not yet by
  enforcement. Branch protection and rulesets both require GitHub Pro on
  a private repository, and this repo stays private until the v1.0 tag
  (`docs/ROADMAP.md`), so neither can be enabled today. **Enable
  protection on `main` — require PRs and require the CI checks in
  `.github/workflows/ci.yml` to pass — as part of going public**, and
  make this line unconditional again then.
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
- New metric → add a row to `docs/METRICS_SPEC.md` §4
- New error code → add a row to `docs/USER_WORKFLOW.md` §6
- New UI screen → add a section to `docs/UI_DESIGN.md` §6

The spec is the contract; code that diverges from spec is a bug.

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

## 10. Roadmap

See `docs/ROADMAP.md` for the phased M1–M5 build plan. New contributors are welcome to pick up any unblocked item — open an issue first so we can coordinate.

---

Thank you for contributing! By participating in this project, you agree to abide by the `CODE_OF_CONDUCT.md`.
