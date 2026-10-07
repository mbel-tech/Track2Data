"""packaging/verify_release.py: SHA256SUMS check and optional gpg verification."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "verify_release", ROOT / "packaging" / "verify_release.py"
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules["verify_release"] = m
    spec.loader.exec_module(m)
    return m


def _release(tmp_path: Path) -> tuple[Path, Path]:
    f = tmp_path / "Track2Data-setup.exe"
    f.write_bytes(b"installer-bytes")
    digest = hashlib.sha256(b"installer-bytes").hexdigest()
    sums = tmp_path / "SHA256SUMS.txt"
    sums.write_text(f"{digest}  {f.name}\n", encoding="utf-8")
    return f, sums


def test_matching_checksum_passes(mod, tmp_path) -> None:
    f, sums = _release(tmp_path)
    assert mod.main([str(f), "--sums", str(sums)]) == 0


def test_tampered_file_fails(mod, tmp_path, capsys) -> None:
    f, sums = _release(tmp_path)
    f.write_bytes(b"tampered")
    assert mod.main([str(f), "--sums", str(sums)]) == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_file_missing_from_sums_fails(mod, tmp_path) -> None:
    f, sums = _release(tmp_path)
    sums.write_text("", encoding="utf-8")
    assert mod.main([str(f), "--sums", str(sums)]) == 1


def test_parse_sums_accepts_binary_marker_and_ignores_blank_lines(mod) -> None:
    text = "\n" + "a" * 64 + " *file.bin\n\n" + "b" * 64 + "  other.bin\n"
    assert mod.parse_sums(text) == {"file.bin": "a" * 64, "other.bin": "b" * 64}


def test_signature_check_reports_missing_gpg(mod, tmp_path, monkeypatch) -> None:
    f, sums = _release(tmp_path)
    sig = tmp_path / (f.name + ".asc")
    sig.write_text("x", encoding="utf-8")
    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    assert mod.main([str(f), "--sums", str(sums), "--sig", str(sig)]) == 2


def test_signature_check_runs_gpg_verify(mod, tmp_path, monkeypatch) -> None:
    f, sums = _release(tmp_path)
    sig = tmp_path / (f.name + ".asc")
    sig.write_text("x", encoding="utf-8")
    calls: list[list[str]] = []

    class _Done:
        returncode = 0

    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/bin/gpg")
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **_kw: (calls.append(cmd), _Done())[1])
    assert mod.main([str(f), "--sums", str(sums), "--sig", str(sig)]) == 0
    assert calls == [["/usr/bin/gpg", "--verify", str(sig), str(f)]]
