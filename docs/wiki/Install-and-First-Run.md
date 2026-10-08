# Install and first run

**Applies to:** Track2Data v0.1.0. The short version is in the
[README](https://github.com/mbel-tech/Track2Data#install); this page is the one that holds
your hand through an unsigned first run.

## 1. Download

From the [Releases page](https://github.com/mbel-tech/Track2Data/releases), take the file for
your system. No Python needed.

| System | File |
|---|---|
| Windows | `Track2Data-setup.exe` (installer) |
| macOS | `Track2Data.dmg` |
| Linux (x86_64) | `Track2Data-x86_64.AppImage` |
| any | `SHA256SUMS.txt` — take this too |

## 2. Verify the download before running it

The binaries are unsigned (step 3), so the checksum is the only thing standing between you
and a corrupted or substituted download. Put `SHA256SUMS.txt` in the same folder and run:

```bash
sha256sum -c SHA256SUMS.txt          # Linux
shasum -a 256 -c SHA256SUMS.txt      # macOS
```

```powershell
Get-FileHash .\Track2Data-setup.exe -Algorithm SHA256   # Windows: compare to the line in SHA256SUMS.txt
```

A mismatch is not a thing to work around: delete the file, download again, and if it
mismatches twice, [open an issue](https://github.com/mbel-tech/Track2Data/issues) before
running it.

## 3. First run: your OS will object

Releases are not code-signed yet. The free signing programme for open-source projects
requires a project to have already published a release, so the first one could not be signed
— the mechanics are in
[`docs/CODE_SIGNING.md`](https://github.com/mbel-tech/Track2Data/blob/main/docs/CODE_SIGNING.md).
Each system complains differently:

- **Windows** — SmartScreen says *"Windows protected your PC"*. Choose **More info**, then
  **Run anyway**.
- **macOS** — Gatekeeper blocks it. **Right-click `Track2Data.app` → Open → Open.** A plain
  double-click reports the app as *damaged*; that is Gatekeeper refusing an unsigned bundle,
  not a bad download — you already checked the download in step 2.
- **Linux** — make the AppImage executable: `chmod +x Track2Data-x86_64.AppImage`, then run
  it. On a minimal system Qt may need its runtime libraries:
  `sudo apt-get install -y libegl1 libxkbcommon-x11-0 libgl1`.

## 4. From source instead

Python 3.11 or newer (3.11 and 3.12 are the versions under CI):

```bash
pip install -e ".[ui]"     # desktop app
track2data-gui

pip install -e "."         # engine + CLI only, no PySide6
track2data --help
```

The desktop extra pulls PySide6 (LGPL, so safe to redistribute under MIT). On Linux, install
the Qt runtime libraries listed above first.

## 5. First five minutes

A complete example project ships with the repository, so you can see the output before
pointing the tool at your own recordings:

```bash
cd examples
track2data run example.t2d.json -o out
```

That writes `out/` with `sessions.csv`, `codebook.csv`, `PROJECT_SUMMARY.md` and a
per-session folder containing `metrics_long.csv` — the table to start from. Then follow the
quick start in the
[user guide](https://github.com/mbel-tech/Track2Data/blob/main/docs/guide/USER_GUIDE.md#quick-start-five-minutes),
and [[Analysis Recipes]] once you have your own export.

## 6. What it writes, and where

| What | Where |
|---|---|
| Project file | `<name>.t2d.json`, wherever you saved it. Keep it with your analysis scripts — it is what makes a run repeatable |
| Preprocessing cache | `.t2d_cache/` beside the project file. Safe to delete; `track2data cache clear --cache-dir <dir>` does it, and `cache stats` reports its size |
| Outputs | the directory you choose on the Export screen, one folder per session, each with `manifest.json` and a `README.md` recording settings, versions and output checksums |

Nothing is written outside those three places, and Track2Data never modifies your
idtracker.ai session folders.

## 7. When something does not work

Open the Run Log (**View ▸ Toggle Run Log**) — failures are reported there with a code and a
remediation. Then check [[FAQ and Troubleshooting]] and the guide's
[troubleshooting table](https://github.com/mbel-tech/Track2Data/blob/main/docs/guide/USER_GUIDE.md#troubleshooting),
and if it is still wrong, paste the Run Log text into an
[issue](https://github.com/mbel-tech/Track2Data/issues).

## 8. Uninstalling

- **Windows** — Settings ▸ Apps ▸ Track2Data ▸ Uninstall.
- **macOS** — drag `Track2Data.app` to the Trash.
- **Linux** — delete the AppImage.
- **From source** — `pip uninstall track2data`.

Then delete any `.t2d_cache/` directories if you want the disk space back. Your project
files and exports are plain files in places you chose; nothing removes them for you.
