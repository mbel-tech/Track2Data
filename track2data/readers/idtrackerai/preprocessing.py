"""
Opportunistic loaders for idtracker.ai's preprocessing/ folder.

Present in 70/70 sessions of the real corpus, but never required --
data_policy can delete it (idtracker.ai_usage.md's data_policy table), and
macOS-synced sessions carry ._* resource-fork noise alongside every real
file (custom_artefacts.py:53 already filters these; the same filter is
used here).

Contents (real, per-session sizes from the corpus):
    ROI_mask.png                    ~10 KB   -- rasterised tracked area
    background.png                 ~530 KB   -- background-subtraction frame
    list_of_fragments.json         ~1.1 MB   -- plain JSON, see fragments.py
    list_of_global_fragments.json   ~25 KB   -- plain JSON, see fragments.py
    list_of_blobs.pickle            ~50 MB   -- pickle; deliberately NOT
                                                loaded here, see blobs.py

Image files are recorded by *path only*, not decoded: track2data's core
engine has no image-decoding dependency (av is optional and video-only;
adding a PNG decoder for a backdrop-only feature is a larger, separate
change than this reader needs). A UI layer with PySide6 already available
can decode them directly via QImage when it needs to render a backdrop.
"""

from __future__ import annotations

from pathlib import Path


def _real_file(path: Path) -> Path | None:
    """Return *path* if it exists and isn't a macOS resource-fork stub."""
    if path.exists() and not path.name.startswith("._"):
        return path
    return None


def find_preprocessing_images(folder: Path) -> dict[str, Path]:
    """
    Return ``{"roi_mask": path, "background": path}`` for whichever of
    ``preprocessing/ROI_mask.png`` / ``background.png`` are present.

    Keys are omitted (not None-valued) when the corresponding file is
    absent, so callers can use ``dict.get(...)`` naturally.
    """
    preproc_dir = Path(folder) / "preprocessing"
    if not preproc_dir.is_dir():
        return {}

    found: dict[str, Path] = {}
    if (p := _real_file(preproc_dir / "ROI_mask.png")) is not None:
        found["roi_mask"] = p
    if (p := _real_file(preproc_dir / "background.png")) is not None:
        found["background"] = p
    return found
