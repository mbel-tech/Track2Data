"""Tests for SHA-256 hashing helpers (file_sha256, dict_sha256)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from track2data.core.hashing import dict_sha256, file_sha256

# ── file_sha256 ──────────────────────────────────────────────────────────────

class TestFileSha256:
    def test_matches_hand_computed_digest(self, tmp_path: Path) -> None:
        content = b"hello track2data\n"
        f = tmp_path / "sample.bin"
        f.write_bytes(content)
        assert file_sha256(f) == hashlib.sha256(content).hexdigest()

    def test_same_file_hashed_twice_gives_same_result(self, tmp_path: Path) -> None:
        f = tmp_path / "stable.bin"
        f.write_bytes(b"some deterministic content")
        assert file_sha256(f) == file_sha256(f)

    def test_different_file_contents_give_different_hash(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"content A")
        f2.write_bytes(b"content B")
        assert file_sha256(f1) != file_sha256(f2)

    def test_empty_file_matches_known_sha256_constant(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        # Well-known SHA-256 digest of the empty byte string.
        assert file_sha256(f) == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert file_sha256(f) == hashlib.sha256(b"").hexdigest()

    def test_chunked_reading_across_multiple_chunks_is_correct(self, tmp_path: Path) -> None:
        # The default chunk_size (64KiB) would read this file in a single pass,
        # which would never exercise the loop's multi-iteration accumulation.
        # Force a tiny chunk_size so h.update() runs many times, and confirm the
        # accumulated digest still matches a single-shot reference hash.
        content = b"0123456789abcdefghijklmnopqrstuvwxyz" * 3
        f = tmp_path / "chunked.bin"
        f.write_bytes(content)
        assert file_sha256(f, chunk_size=8) == hashlib.sha256(content).hexdigest()

    def test_digest_is_valid_lowercase_hex_of_correct_length(self, tmp_path: Path) -> None:
        f = tmp_path / "x.bin"
        f.write_bytes(b"abc")
        digest = file_sha256(f)
        assert isinstance(digest, str)
        assert len(digest) == 64
        assert digest == digest.lower()
        int(digest, 16)  # raises ValueError if not valid hex


# ── dict_sha256 ──────────────────────────────────────────────────────────────

class TestDictSha256:
    def test_same_content_gives_same_hash(self) -> None:
        d1 = {"a": 1, "b": 2}
        d2 = {"a": 1, "b": 2}
        assert dict_sha256(d1) == dict_sha256(d2)

    def test_different_values_give_different_hash(self) -> None:
        assert dict_sha256({"a": 1}) != dict_sha256({"a": 2})

    def test_key_order_does_not_affect_hash(self) -> None:
        # dict_sha256 JSON-serialises with sort_keys=True, so insertion order
        # of the source dict must not change the resulting digest.
        assert dict_sha256({"a": 1, "b": 2}) == dict_sha256({"b": 2, "a": 1})

    def test_matches_hand_computed_digest(self) -> None:
        data = {"z": 1, "a": [1, 2, 3], "m": "text"}
        expected = hashlib.sha256(
            json.dumps(data, sort_keys=True, default=str).encode()
        ).hexdigest()
        assert dict_sha256(data) == expected

    def test_non_json_native_value_uses_str_fallback(self) -> None:
        # `default=str` means values json can't natively serialise (e.g. Path)
        # are stringified rather than raising a TypeError.
        data = {"path": Path("some/file.txt")}
        expected = hashlib.sha256(
            json.dumps(data, sort_keys=True, default=str).encode()
        ).hexdigest()
        assert dict_sha256(data) == expected

    def test_digest_is_valid_lowercase_hex_of_correct_length(self) -> None:
        digest = dict_sha256({"x": 1})
        assert isinstance(digest, str)
        assert len(digest) == 64
        assert digest == digest.lower()
        int(digest, 16)  # raises ValueError if not valid hex
