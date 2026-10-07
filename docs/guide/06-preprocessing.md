# 6 · Preprocessing

![Preprocessing screen](images/06-preprocessing.png)

Cleaning applied to the trajectories before any metric is computed. Defaults suit most data. Every
step has an **Enabled** box; the raw data is never overwritten.

| Step | What it does |
|---|---|
| **Gap fill** | Linearly interpolates tracking gaps up to *Max gap frames* |
| **Jump detection** | Finds implausible position jumps (standard-deviation multiple, percentile, or idtracker.ai's own velocity threshold) and replaces them |
| **Identity switch correction** | See below. Off by default |
| **Smoothing** | Moving average or Savitzky–Golay, over *Window* frames |
| **Coverage gate** | Warns when more than *Max NaN fraction* of an animal's frames are missing |

![Identity switch correction](images/06-preprocessing-identity-switch.png)

**Identity switch correction is experimental and off by default.** It reassigns identities from
geometry alone, ignoring idtracker.ai's own fragment boundaries. On a real recording it re-permuted a
large share of frames and inflated path length enormously. Leave it off unless you have checked the
result in [Preview ▸ Trajectories](09-preview.md) with *Raw + processed* shown.

Settings you change here are saved automatically and used for the next run.
