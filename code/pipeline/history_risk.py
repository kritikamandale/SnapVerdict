from __future__ import annotations

from pipeline.load_data import ClaimRecord


def extract_history_flags(claim: ClaimRecord) -> list[str]:
    """Return the risk flags stored in user_history.csv for this user.

    Passes through history_flags as-is — no escalation logic is applied here.
    user_history.csv already encodes the adjudicated flags for each user
    (e.g. user_history_risk, manual_review_required); the pipeline should not
    add flags that the history CSV did not assert.
    """
    return list(claim.get("history_flags", []))
