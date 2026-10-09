"""Qt-free pairing of top/side sessions and fish-map checks."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PairingResult:
    pairs: list[tuple[str, str]] = field(default_factory=list)
    top_ids: list[str] = field(default_factory=list)
    side_ids: list[str] = field(default_factory=list)
    unpaired_top: list[str] = field(default_factory=list)
    unpaired_side: list[str] = field(default_factory=list)
    ambiguous_keys: list[str] = field(default_factory=list)
    both_roles: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def fish_labels(identities_labels: Sequence[str] | None, n_animals: int) -> list[str]:
    if identities_labels:
        return [str(x) for x in identities_labels]
    return [str(i) for i in range(n_animals)]


def _compile(pattern: str, name: str, errors: list[str]) -> re.Pattern[str] | None:
    if not pattern:
        return None
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        errors.append(f"{name} regex is invalid: {exc}")
        return None
    if "key" not in rx.groupindex:
        errors.append(f"{name} regex needs a (?P<key>...) group")
        return None
    return rx


def pair_by_regex(session_ids: Sequence[str], top_regex: str, side_regex: str) -> PairingResult:
    errors: list[str] = []
    top_rx = _compile(top_regex, "top", errors)
    side_rx = _compile(side_regex, "side", errors)

    top: list[tuple[str, str]] = []
    side: list[tuple[str, str]] = []
    both: list[str] = []
    for sid in session_ids:
        tm = top_rx.search(sid) if top_rx else None
        sm = side_rx.search(sid) if side_rx else None
        # A missing or empty key group means the session does not match the role.
        if tm and not tm.group("key"):
            tm = None
        if sm and not sm.group("key"):
            sm = None
        if tm and sm:
            both.append(sid)
        elif tm:
            top.append((sid, tm.group("key")))
        elif sm:
            side.append((sid, sm.group("key")))

    def _by_key(items: list[tuple[str, str]]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for sid, key in items:
            out.setdefault(key, []).append(sid)
        return out

    top_by, side_by = _by_key(top), _by_key(side)
    ambiguous: list[str] = []
    ambiguous_set: set[str] = set()
    for key in [k for _, k in top] + [k for _, k in side]:
        if key in ambiguous_set:
            continue
        if len(top_by.get(key, [])) > 1 or len(side_by.get(key, [])) > 1:
            ambiguous.append(key)
            ambiguous_set.add(key)

    pairs: list[tuple[str, str]] = []
    paired_top: set[str] = set()
    paired_side: set[str] = set()
    for sid, key in top:
        if key in ambiguous_set or key not in side_by:
            continue
        partner = side_by[key][0]
        pairs.append((sid, partner))
        paired_top.add(sid)
        paired_side.add(partner)

    return PairingResult(
        pairs=pairs,
        top_ids=[s for s, _ in top],
        side_ids=[s for s, _ in side],
        unpaired_top=[s for s, _ in top if s not in paired_top],
        unpaired_side=[s for s, _ in side if s not in paired_side],
        ambiguous_keys=ambiguous,
        both_roles=both,
        errors=errors,
    )


def identity_map(
    top_labels: Sequence[str], side_labels: Sequence[str]
) -> tuple[dict[str, str], list[str]]:
    side_set = set(side_labels)
    top_set = set(top_labels)
    mapping = {lab: lab for lab in top_labels if lab in side_set}
    only_one = sorted(top_set ^ side_set)
    return mapping, only_one


def validate_fish_map(
    fish_map: Mapping[str, str],
    top_labels: Sequence[str],
    side_labels: Sequence[str],
    *,
    top_identity_free: bool,
    side_identity_free: bool,
) -> list[str]:
    msgs: list[str] = []
    if top_identity_free or side_identity_free:
        msgs.append("cannot match fish: this session has no stable identities")
    if len(top_labels) != len(side_labels):
        msgs.append(f"{len(top_labels)} top fish vs {len(side_labels)} side fish")
    top_set, side_set = set(top_labels), set(side_labels)
    for t in fish_map:
        if t not in top_set:
            msgs.append(f"unknown top fish: {t}")
    unknown_side: list[str] = []
    for s in fish_map.values():
        if s not in side_set and s not in unknown_side:
            unknown_side.append(s)
    msgs.extend(f"unknown side fish: {s}" for s in unknown_side)
    seen: set[str] = set()
    dup: list[str] = []
    for s in fish_map.values():
        if s in seen and s not in dup:
            dup.append(s)
        seen.add(s)
    for s in dup:
        msgs.append(f"duplicate side fish: {s}")
    return msgs
