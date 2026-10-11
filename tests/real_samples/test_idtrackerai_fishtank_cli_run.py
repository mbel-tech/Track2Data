"""One long idtracker.ai 4.0.9 recording (463,997 frames), driven through the command line.

The file is one member of a Zenodo record (10.5281/zenodo.10103747, FishTank*.zip).
It is fetched with HTTP range requests (the archive is not downloaded whole), checked against a pinned
SHA-256 of the member, and cached beside the other fixtures. The test skips when the network is off
(``T2D_FIXTURES_OFFLINE=1``) or the download fails.

It takes about two minutes, so it is also marked ``slow``. Run:
    pytest tests/real_samples/test_idtrackerai_fishtank_cli_run.py -m contract

The video size is a placeholder (the file records none): only the mechanics are tested.
"""
from __future__ import annotations

import hashlib
import io
import logging
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from click.testing import CliRunner

from tests.real_samples.fixtures import CACHE, OFFLINE
from track2data.cli import cli
from track2data.core.manifest import read as read_manifest
from track2data.core.manifest import write as write_manifest

pytestmark = [pytest.mark.contract, pytest.mark.slow]

ZIP = "FishTank20200207_161445"
URL = f"https://zenodo.org/api/records/10103747/files/{ZIP}.zip/content"
MEMBER = f"{ZIP}/idtracker_results/trajectories.npy"
SHA256 = "236015ade4082b9f6c166619976f349b8234ab4b2caf9188e76a5a47d3273d63"
FRAMES, ANIMALS = 463997, 2
_HEADERS = {"User-Agent": "t2d-reader-fixture-tests"}


class _RangeFile(io.RawIOBase):
    """A read-only seekable view of a remote file, fetched with HTTP range requests."""

    def __init__(self, url: str) -> None:
        self.url, self.pos = url, 0
        request = urllib.request.Request(url, headers={**_HEADERS, "Range": "bytes=0-0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            self.size = int(response.headers["Content-Range"].split("/")[1])
            response.read()

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def readinto(self, buffer) -> int:
        n = min(len(buffer), self.size - self.pos)
        if n <= 0:
            return 0
        request = urllib.request.Request(
            self.url, headers={**_HEADERS, "Range": f"bytes={self.pos}-{self.pos + n - 1}"}
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read()
        buffer[: len(data)] = data
        self.pos += len(data)
        return len(data)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fishtank_member() -> Path:
    """The cached, hash-verified trajectories.npy of the 4.0.9 FishTank recording."""
    path = CACHE / f"{ZIP}.trajectories.npy"
    if not path.exists():
        if OFFLINE:
            pytest.skip(f"{path.name} not cached and T2D_FIXTURES_OFFLINE=1")
        CACHE.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".part")
        try:
            archive = zipfile.ZipFile(io.BufferedReader(_RangeFile(URL), buffer_size=8 * 1024 * 1024))
            with archive.open(MEMBER) as source, open(partial, "wb") as target:
                for chunk in iter(lambda: source.read(1 << 20), b""):
                    target.write(chunk)
        except Exception as exc:  # a network failure is not a test failure
            partial.unlink(missing_ok=True)
            pytest.skip(f"cannot download {ZIP}: {exc}")
        partial.replace(path)
    digest = _sha256(path)
    assert digest == SHA256, f"{path.name} is {digest}, expected {SHA256}; delete it to fetch it again"
    return path


def _invoke(*args: str):
    return CliRunner().invoke(cli, list(args))


def test_a_long_4_0_9_recording_goes_through_add_validate_and_run(tmp_path, caplog):
    member = _fishtank_member()
    session = tmp_path / "data" / "fishtank"
    (session / "trajectories").mkdir(parents=True)
    (session / "trajectories" / "trajectories.npy").write_bytes(member.read_bytes())

    project = tmp_path / "fishtank.t2d.json"
    assert _invoke("new", "fishtank", "-o", str(project)).exit_code == 0
    manifest = read_manifest(project)
    manifest.metrics.individual, manifest.metrics.group = ["IL-1", "IL-2"], ["GL-1"]
    manifest.metrics.diagnostic = ["D-1"]
    write_manifest(manifest, project)

    added = _invoke("add", str(project), str(session), "--yes", "--allow-pickle",
                    "--option=width_px=1000", "--option=height_px=1000")
    assert added.exit_code == 0, added.output
    validated = _invoke("validate", str(project))
    assert validated.exit_code == 0, validated.output
    out = tmp_path / "out"
    with caplog.at_level(logging.INFO):
        ran = _invoke("run", str(project), "-o", str(out), "-e", "csv_long", "-e", "readme")
    assert ran.exit_code == 0, ran.output

    # A 4.x file is known to read: its version note is information, not a warning.
    loud = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert not any("IDT_VERSION_UNKNOWN" in r.getMessage() for r in loud)
    assert "IDT_VERSION_UNKNOWN" not in ran.output.replace("INFO", "")
    # The project keeps the default body-length calibration, so the README explains *_cm.
    readme = (out / "fishtank" / "README.md").read_text(encoding="utf-8")
    assert "## Units" in readme

    frames = pd.read_csv(out / "fishtank" / "master_fish_by_frame.csv")
    assert len(frames) == FRAMES * ANIMALS
    assert frames["individual_id"].nunique() == ANIMALS
    assert frames["x_px"].notna().any()
