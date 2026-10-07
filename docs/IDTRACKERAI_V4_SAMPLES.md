# Help add idtracker.ai v4 support: send us a sample

Track2Data reads idtracker.ai 6.x output (and the legacy v5 layout). **v4 is not
supported yet**, because no v4 output exists in this repository to build and test a
reader against, and a reader written from memory would only validate itself against
its own assumptions ([D-012](../DECISIONS.md)). If you have v4 output, a small sample
is all that is needed.

When you open a v4 folder today, Track2Data says so (`V4_NOT_SUPPORTED`) instead of
the generic "no reader recognised the folder". That check is a heuristic: a folder with
`video_object.npy` and `preprocessing/blobs_collection*.npy`, directly or inside a
`session_*` folder. It does not claim anything more about the layout.

## What to send

1. **Two or three session folders** (zip them), ideally covering:
   - a session with tracking gaps (frames where an animal is missing);
   - a session tracked **without** identification (no stable identities);
   - a session with a different number of animals.
   Small or shortened videos are fine; the trajectories matter, not the video.
2. **A file listing:** `find <folder> -type f | sort` (Linux/macOS) or
   `Get-ChildItem -Recurse -File` (PowerShell).
3. **The inspector output**, run on the same folders:

   ```bash
   python scripts/inspect_idtrackerai_output.py <session_folder> > v4_layout.txt
   ```

   This lists files and the structure of each `.npy` (shapes, dtypes, dict keys, NaN
   counts) and needs only numpy. idtracker.ai stores some objects as pickles, which can
   execute code when loaded, so by default those files are **listed but not opened**.
   If you made the folder yourself and are happy to trust it, add `--allow-pickle` for
   the fuller report.
4. **Versions and facts:** idtracker.ai version, Python and numpy versions, and the real
   frames per second, width, height and number of frames of each video.
5. Whether you are comfortable with Track2Data loading pickled `.npy` files from such
   folders (the v6 reader already has to for some files).

Attach these to a GitHub issue. Please do not post data that is not yours to share.

## What happens next

With real samples, the v4 reader gets implemented test-first against them, the
`idtrackerai_v4` entry point is re-added (D-012 says to do so only then), and the "v4 is
not supported yet" wording in the docs is removed.
