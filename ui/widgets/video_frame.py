"""The first frame of a session's video as a QImage, for use as a backdrop.

Shared by the panel editor's preview and the zones canvas. Zones are stored in the video's
declared pixel space, so a frame is only ever returned when the decoder reports exactly that
size: a different frame would put every vertex in the wrong picture.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QImage

from track2data.readers.video_meta import extract_frame_rgb


def decode_first_frame(video_path: Path | None, width_px: int, height_px: int) -> QImage | None:
    """The first frame of *video_path*, or None when it cannot be used as a backdrop.

    None when there is no readable video, the declared size is unknown (not positive), the
    decoder fails, or the decoded frame is not ``width_px`` x ``height_px``. The size is
    compared as decoded dimensions, not as a byte count: a rotated frame (1080x1920 against a
    declared 1920x1080) has the same ``w * h * 3`` bytes.
    """
    if video_path is None or width_px <= 0 or height_px <= 0 or not Path(video_path).exists():
        return None
    try:
        frame = extract_frame_rgb(Path(video_path), 0)
    except Exception:
        return None
    if frame is None:
        return None
    data, width, height = frame
    if (width, height) != (width_px, height_px) or len(data) != width_px * height_px * 3:
        return None
    # copy() so the image owns its pixels and not the bytes object
    return QImage(data, width_px, height_px, width_px * 3, QImage.Format.Format_RGB888).copy()
