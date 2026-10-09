import re

from jarvis.schemas import PermissionLevel

HIGH_IMPACT_PATTERNS = (
    r"\b(?:buy|purchase|order|checkout|pay|spend)\b",
    r"\b(?:send|email|message|contact|call)\b",
    r"\b(?:submit|apply|publish|post)\b",
    r"\b(?:delete|remove|erase|destroy|overwrite)\b",
    r"\b(?:execute|run)\b.{0,30}\b(?:shell|command|script)\b",
)
PREPARE_PATTERNS = (
    r"\b(?:draft|prepare|write|create|generate|plan|analyze|research|summarize)\b",
)


def classify_permission(goal: str) -> PermissionLevel:
    normalized = goal.casefold()
    if any(re.search(pattern, normalized) for pattern in HIGH_IMPACT_PATTERNS):
        return PermissionLevel.HIGH_IMPACT
    if any(re.search(pattern, normalized) for pattern in PREPARE_PATTERNS):
        return PermissionLevel.PREPARE
    return PermissionLevel.READ
