"""Report which release-signing platforms are fully configured.

Reads secret *names* from the environment (values are never printed) and
classifies each platform as:

* ``sign``    -- every required secret is set;
* ``skip``    -- none is set (the release is published unsigned);
* ``partial`` -- some but not all are set, which is a misconfiguration: the
  job fails here, with the missing names, instead of half-way through signing.

``REQUIRED`` must match ``docs/CODE_SIGNING.md`` section 3 and the secrets
referenced by ``.github/workflows/release.yml`` (a test enforces both).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED: dict[str, tuple[str, ...]] = {
    "macos": (
        "MACOS_CERTIFICATE_P12",
        "MACOS_CERTIFICATE_PASSWORD",
        "MACOS_SIGNING_IDENTITY",
        "MACOS_NOTARY_APPLE_ID",
        "MACOS_NOTARY_PASSWORD",
        "MACOS_NOTARY_TEAM_ID",
    ),
    "windows": ("WINDOWS_CERT_PFX_BASE64", "WINDOWS_CERT_PASSWORD"),
    "linux": ("GPG_PRIVATE_KEY", "GPG_PASSPHRASE"),
}

#: Workflow output name per platform (the Linux step is gated on ``gpg``).
OUTPUT_NAME = {"macos": "macos", "windows": "windows", "linux": "gpg"}


@dataclass
class Readiness:
    state: str  # "sign" | "skip" | "partial"
    missing: list[str] = field(default_factory=list)


def assess(environ: Mapping[str, str]) -> dict[str, Readiness]:
    """Classify every platform from the names present (non-blank) in *environ*."""
    result: dict[str, Readiness] = {}
    for platform, names in REQUIRED.items():
        missing = [n for n in names if not environ.get(n, "").strip()]
        if not missing:
            result[platform] = Readiness("sign")
        elif len(missing) == len(names):
            result[platform] = Readiness("skip")
        else:
            result[platform] = Readiness("partial", missing)
    return result


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--github-output", type=Path, help="append macos/windows/gpg=true|false")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)

    result = assess(os.environ if environ is None else environ)

    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as fh:
            for platform, r in result.items():
                fh.write(f"{OUTPUT_NAME[platform]}={'true' if r.state == 'sign' else 'false'}\n")

    if args.json:
        print(json.dumps({p: {"state": r.state, "missing": r.missing} for p, r in result.items()}))
    else:
        for platform, r in result.items():
            line = f"{platform}: {r.state}"
            if r.missing:
                line += " -- missing " + ", ".join(r.missing)
            print(line)

    broken = [p for p, r in result.items() if r.state == "partial"]
    if broken:
        print(
            "ERROR: incomplete signing secrets for " + ", ".join(broken)
            + ". Set all of them (docs/CODE_SIGNING.md section 3) or none.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
