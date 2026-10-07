"""packaging/check_signing_readiness.py: which platforms will sign, skip or fail."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "check_signing_readiness", ROOT / "packaging" / "check_signing_readiness.py"
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules["check_signing_readiness"] = m
    spec.loader.exec_module(m)
    return m


FULL = {
    "macos": [
        "MACOS_CERTIFICATE_P12", "MACOS_CERTIFICATE_PASSWORD", "MACOS_SIGNING_IDENTITY",
        "MACOS_NOTARY_APPLE_ID", "MACOS_NOTARY_PASSWORD", "MACOS_NOTARY_TEAM_ID",
    ],
    "windows": ["WINDOWS_CERT_PFX_BASE64", "WINDOWS_CERT_PASSWORD"],
    "linux": ["GPG_PRIVATE_KEY", "GPG_PASSPHRASE"],
}


def _env(*platforms: str, drop: tuple[str, ...] = ()) -> dict[str, str]:
    env = {name: "x" for p in platforms for name in FULL[p] if name not in drop}
    return env


def test_required_secrets_are_the_documented_ones(mod) -> None:
    assert {k: list(v) for k, v in mod.REQUIRED.items()} == FULL


def test_no_secrets_means_every_platform_is_skipped(mod) -> None:
    result = mod.assess({})
    assert {p: r.state for p, r in result.items()} == {
        "macos": "skip", "windows": "skip", "linux": "skip"
    }


def test_a_complete_set_means_sign(mod) -> None:
    result = mod.assess(_env("windows"))
    assert result["windows"].state == "sign" and result["windows"].missing == []
    assert result["macos"].state == "skip"


def test_a_partial_set_names_exactly_what_is_missing(mod) -> None:
    result = mod.assess(_env("macos", drop=("MACOS_NOTARY_TEAM_ID", "MACOS_SIGNING_IDENTITY")))
    assert result["macos"].state == "partial"
    assert result["macos"].missing == ["MACOS_SIGNING_IDENTITY", "MACOS_NOTARY_TEAM_ID"]


def test_gpg_key_without_passphrase_is_partial(mod) -> None:
    assert mod.assess({"GPG_PRIVATE_KEY": "k"})["linux"].state == "partial"


def test_blank_and_whitespace_values_count_as_unset(mod) -> None:
    env = _env("windows")
    env["WINDOWS_CERT_PASSWORD"] = "   "
    result = mod.assess(env)
    assert result["windows"].state == "partial"
    assert result["windows"].missing == ["WINDOWS_CERT_PASSWORD"]


def test_cli_exit_codes(mod, capsys) -> None:
    assert mod.main([], environ={}) == 0                                   # all skipped: fine
    assert mod.main([], environ=_env("linux")) == 0                        # complete: fine
    assert mod.main([], environ=_env("macos", drop=("MACOS_NOTARY_PASSWORD",))) == 1


def test_cli_never_prints_secret_values(mod, capsys) -> None:
    env = {name: "SUPER-SECRET-VALUE" for name in FULL["linux"] + FULL["windows"][:1]}
    mod.main([], environ=env)
    out = capsys.readouterr()
    assert "SUPER-SECRET-VALUE" not in out.out + out.err
    assert "GPG_PRIVATE_KEY" in out.out + out.err or "linux" in out.out


def test_github_output_file_gets_booleans_the_workflow_can_gate_on(mod, tmp_path) -> None:
    out = tmp_path / "gh_output"
    mod.main(["--github-output", str(out)], environ=_env("windows", "linux"))
    lines = dict(line.split("=", 1) for line in out.read_text().splitlines())
    assert lines == {"macos": "false", "windows": "true", "gpg": "true"}


def test_partial_set_still_writes_false_so_nothing_half_signs(mod, tmp_path) -> None:
    out = tmp_path / "gh_output"
    rc = mod.main(["--github-output", str(out)], environ=_env("macos", drop=("MACOS_NOTARY_ID",)))
    assert rc == 0  # nothing missing from a complete set was dropped (name above is not real)
    rc = mod.main(
        ["--github-output", str(out)],
        environ=_env("macos", drop=("MACOS_NOTARY_PASSWORD",)),
    )
    assert rc == 1
    assert "macos=false" in out.read_text()


def test_json_output(mod, capsys) -> None:
    mod.main(["--json"], environ=_env("windows"))
    data = json.loads(capsys.readouterr().out)
    assert data["windows"] == {"state": "sign", "missing": []}
    assert data["macos"]["state"] == "skip"


# ── the workflow, the docs and the checker must agree ─────────────────────────


def _workflow_secrets() -> set[str]:
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    return set(re.findall(r"secrets\.([A-Z0-9_]+)", text)) - {"GITHUB_TOKEN"}


def test_release_workflow_uses_exactly_the_secrets_the_checker_knows(mod) -> None:
    known = {s for names in mod.REQUIRED.values() for s in names}
    assert _workflow_secrets() == known, (
        "release.yml and packaging/check_signing_readiness.py disagree about secret names; "
        "update REQUIRED (and docs/CODE_SIGNING.md) together"
    )


def test_every_secret_is_documented(mod) -> None:
    doc = (ROOT / "docs" / "CODE_SIGNING.md").read_text(encoding="utf-8")
    for names in mod.REQUIRED.values():
        for name in names:
            assert f"`{name}`" in doc, f"{name} is not documented in docs/CODE_SIGNING.md"


def test_workflow_gates_signing_on_the_checker_not_on_a_single_secret() -> None:
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "packaging/check_signing_readiness.py" in text
    assert '[ -n "$MACOS_CERT" ] && macos=true' not in text
