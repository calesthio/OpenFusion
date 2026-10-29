"""Judge/critic verdict schema.

{"assessment": "approve" | "revise", "score": 1-5,
 "rationale": str, "defect": {"target": str, "evidence": str} | null}
"""
from __future__ import annotations

import json
import re
from typing import Any

SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["assessment", "score", "rationale"],
    "properties": {
        "assessment": {"enum": ["approve", "revise"]},
        "score": {"type": "integer", "minimum": 1, "maximum": 5},
        "rationale": {"type": "string"},
        "defect": {
            "type": ["object", "null"],
            "properties": {"target": {"type": "string"}, "evidence": {"type": "string"}},
        },
    },
}


def parse_verdict(text: str) -> dict[str, Any]:
    """Extract and validate the last JSON object in a judge reply.

    Raises ValueError if missing/invalid; callers should treat that as 'revise'
    (fail closed: an unparseable review never silently approves).
    """
    candidates = re.findall(r"\{.*\}", text, re.S)
    if not candidates:
        raise ValueError("no JSON verdict found")
    data = json.loads(candidates[-1])
    if data.get("assessment") not in ("approve", "revise"):
        raise ValueError("assessment must be approve|revise")
    score = data.get("score")
    if not isinstance(score, int) or not 1 <= score <= 5:
        raise ValueError("score must be an int 1-5")
    if not isinstance(data.get("rationale"), str):
        raise ValueError("rationale must be a string")
    if data["assessment"] == "revise" and not data.get("defect"):
        raise ValueError("revise verdict must name a concrete defect")
    return data


def should_escalate(text: str) -> bool:
    try:
        return parse_verdict(text)["assessment"] == "revise"
    except (ValueError, json.JSONDecodeError):
        return True
