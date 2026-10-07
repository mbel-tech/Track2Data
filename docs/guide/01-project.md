# 1 · Project

![Project screen](images/01-project.png)

A project is one `.t2d.json` file next to a folder of results. It stores every setting on the
following screens, so you can close the app and pick up later, or re-run the identical analysis
from the command line.

**Do this**

1. **File ▸ New project…**, enter a name, choose a folder. Or **File ▸ Open project…** for an
   existing `.t2d.json`.
2. Track2Data moves straight on to [Sessions](02-sessions.md).

**Notes**

- **File ▸ Save project** writes the file; settings are also kept in memory as you edit.
- Reopening a project re-reads each session folder in the background, so frame counts and
  calibration readiness appear again after a moment.
- Preprocessed sessions are cached in `.t2d_cache/` inside the project folder. It is safe to delete
  (`track2data cache clear --cache-dir <dir>` does it too); it is rebuilt when needed.
