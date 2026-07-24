from __future__ import annotations

import re

from review_prep.models import ParsedCl

# Label + number; accepts "CL is N" or "CL N"
_CL_RE = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z0-9 /_-]*?)\s+CL(?:\s+is)?\s+(?P<number>\d+)",
    re.IGNORECASE,
)


def parse_cls_from_comment(text: str) -> list[ParsedCl]:
    results: list[ParsedCl] = []
    for match in _CL_RE.finditer(text or ""):
        label = " ".join(match.group("label").strip().split())
        # Normalize known casing
        known = {"source art": "Source Art", "preflight": "Preflight", "wip": "WIP"}
        label = known.get(label.lower(), label)
        results.append(
            ParsedCl(label=label, number=int(match.group("number")), raw=match.group(0))
        )
    return results


def is_delivery_comment(text: str) -> bool:
    return bool(parse_cls_from_comment(text))
