# Compatibility

**Applies to:** Track2Data v0.1.0 and `main` as of 2026-10-08. Reader support changes
between releases; the [changelog](https://github.com/mbel-tech/Track2Data/blob/main/CHANGELOG.md)
is authoritative.

## Tracker output

| Input | Status | Notes |
|---|---|---|
| **idtracker.ai 6.x** output folder | **Supported** | The primary reader. Pick the session folder itself — the one containing `trajectories/` |
| **idtracker.ai v5** (legacy layout) | **Supported** | Reads, but carries no body length: on the default body-length calibration those sessions export in pixels only, and the run says so |
| **idtracker.ai v4** | **Not supported** | A v4-looking folder fails with `V4_NOT_SUPPORTED` rather than being misread. Blocked on real sample folders — see [`docs/IDTRACKERAI_V4_SAMPLES.md`](https://github.com/mbel-tech/Track2Data/blob/main/docs/IDTRACKERAI_V4_SAMPLES.md) |
| **Other trackers** | **In progress** | The foundation is in place (declared reader options, saved reader per session, confirm-before-add); no second tracker has shipped |

`track2data list-readers` prints what this build can read and which options each reader
needs; `track2data scan ROOT` says which software wrote a folder, with the evidence.

A session is always read by the reader it was added with. If that reader is missing from the
build you are running, you get `READER_NOT_AVAILABLE` — Track2Data will not substitute
another one, because the same files read differently can be different numbers.

### Formats recognised but not readable

A scan names these rather than reporting "nothing recognised", and says what to export
instead: SLEAP `.slp` projects (export the Analysis HDF5), `trx.mat`, FlyTracker
`-track.mat`, DANNCE `save_data_AVG.mat`, Multi-Worm Tracker `.blobs`, AnimalTA detailed
files, DeepLabCut 3-D tables, and FicTrac logs.

### Pickled trajectories

idtracker.ai can write `trajectories.npy` as a pickle, and loading a pickle executes
whatever code is in it. Track2Data refuses by default; reading one needs the explicit
`security.allow_pickle_trajectories` opt-in. The same gate governs blob-layer features
(D-15's correction census, `body_length_source = "blobs"`). See
[`SECURITY.md`](https://github.com/mbel-tech/Track2Data/blob/main/SECURITY.md).

## Operating systems

| OS | Install route | Built and tested on |
|---|---|---|
| Windows | `Track2Data-setup.exe` installer | `windows-2022` runner image, Python 3.11 |
| macOS | `Track2Data.dmg` | `macos-26` runner image, Python 3.11 |
| Linux (x86_64) | `Track2Data-x86_64.AppImage` | `ubuntu-22.04` runner image, Python 3.11 and 3.12 |

All three are **unsigned** — see [[Install and First Run]] for the first-run dialogs, and
[[Known Issues]]. On a minimal Linux system Qt needs `libegl1`, `libxkbcommon-x11-0` and
`libgl1`.

## Python, if you install from source

- **Requires Python ≥ 3.11.** CI covers 3.11 and 3.12 on Linux; Windows and macOS are
  covered on 3.11.
- `pip install -e "."` — engine and CLI, no GUI dependency.
- `pip install -e ".[ui]"` — adds PySide6 ≥ 6.6 for the desktop app (`track2data-gui`).
- `pip install -e ".[dev]"` — tests and linting; `".[docs]"` — the documentation site.

Pull requests run the Linux matrix only; pushes to `main` and release tags run all three
operating systems.

## Reading the output elsewhere

Exports are CSV, Feather and Excel, with a `codebook.csv` of units and DOIs — no
Track2Data-specific format to parse. Column conventions and the planned `movement` mapping
are in [[Formats and Interoperability]] and
[`docs/INTEROPERABILITY.md`](https://github.com/mbel-tech/Track2Data/blob/main/docs/INTEROPERABILITY.md).
Note Excel's row limit: past it, the per-frame table continues on a second sheet, so use the
CSV or Feather file when you need the complete table.
