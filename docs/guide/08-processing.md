# 8 · Processing

![Processing screen](images/08-processing.png)

**Validate pipeline** checks the project and lists anything that would stop a run. **Run pipeline**
(or the toolbar button, or Ctrl+R) processes every session: import, preprocessing, calibration,
zone assignment, metrics, export.

- The table shows each session's status and duration. A failed session is marked *Failed* and does
  not stop the others.
- **Workers** sets how many sessions run at the same time. `1` runs them one after another. More
  workers help when each session takes many seconds or more; for short sessions the start-up cost
  of each worker makes it slower.
- **Cancel** stops the run at the next safe point (between sessions, preprocessing steps or
  metrics).
- Preprocessed sessions are cached, so re-running after changing only metrics or export settings
  skips the slow parts.

Results are written to `<project>/exports/<timestamp>/<session>/`.
