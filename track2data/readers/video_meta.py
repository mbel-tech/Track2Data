"""
Video frame extraction for the preview layer.

Uses pyav (optional dependency) to extract a single frame from the source
video.  If pyav is not installed or the video file is unreachable the
caller receives None and the UI falls back to a blank canvas.
"""

from __future__ import annotations

from pathlib import Path


def extract_frame(video_path: Path, frame_index: int = 0) -> bytes | None:
    """
    Return raw RGB bytes for *frame_index* or None on any failure.
    Requires the optional 'video' extra (pip install track2data[video]).
    """
    try:
        import av
    except ImportError:
        return None

    try:
        with av.open(str(video_path)) as container:
            stream = container.streams.video[0]
            stream.codec_context.skip_frame = "NONREF"
            for i, frame in enumerate(container.decode(stream)):
                if i == frame_index:
                    return bytes(frame.to_image().tobytes())
    except Exception:
        return None
    return None
