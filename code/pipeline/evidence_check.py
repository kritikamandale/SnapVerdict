from __future__ import annotations

from typing import TypedDict

import pandas as pd


class EvidenceSufficiencyResult(TypedDict):
    evidence_standard_met: bool
    evidence_standard_met_reason: str


def check_evidence_sufficiency(
    claim_object: str,
    image_paths: list[str],
    evidence_requirements_df: pd.DataFrame,
) -> EvidenceSufficiencyResult:
    """Deterministic evidence-sufficiency check — no vision call.

    Looks up applicable requirement rows by claim_object (exact match first,
    then 'all' rows as the universal baseline). Compares the submitted image
    count against the structural minimum implied by those requirements and
    returns evidence_standard_met + a reason string that cites the matched rule.

    What this can decide without vision:
      - 0 images submitted → False (nothing to evaluate)
      - unrecognised claim_object with no matching requirements → False

    What only vision can decide (so this stage returns True as a structural
    baseline and lets vision_inspect / decide.py override):
      - images submitted but wrong angle / part not in frame
      - images submitted but too blurry / obstructed to assess
      - images submitted but show wrong object
    """
    # --- 1. Requirement lookup ---
    object_rows = evidence_requirements_df[
        evidence_requirements_df["claim_object"] == claim_object
    ]
    all_rows = evidence_requirements_df[
        evidence_requirements_df["claim_object"] == "all"
    ]

    # If no object-specific rule exists, fall back to the "all" rows only.
    using_fallback = object_rows.empty
    if using_fallback:
        applicable = all_rows.reset_index(drop=True)
    else:
        applicable = pd.concat([object_rows, all_rows], ignore_index=True)

    if applicable.empty:
        return {
            "evidence_standard_met": False,
            "evidence_standard_met_reason": (
                f"No evidence requirements defined for claim_object='{claim_object}'."
            ),
        }

    # --- 2. Image count comparison ---
    image_count = len(image_paths)

    if image_count == 0:
        # Cite the general baseline requirement so the reason is self-contained.
        baseline_mask = applicable["requirement_id"] == "REQ_GENERAL_OBJECT_PART"
        anchor = (
            applicable[baseline_mask].iloc[0]
            if baseline_mask.any()
            else applicable.iloc[0]
        )
        return {
            "evidence_standard_met": False,
            "evidence_standard_met_reason": (
                f"No images submitted; fails {anchor['requirement_id']}: "
                f"{anchor['minimum_image_evidence']}"
            ),
        }

    # --- 3. Structural minimum met ---
    req_ids = applicable["requirement_id"].tolist()
    req_ids_str = "; ".join(req_ids)
    noun = f"{image_count} image{'s' if image_count > 1 else ''}"

    fallback_note = (
        f" No {claim_object}-specific requirement found; applied 'all' rules."
        if using_fallback
        else ""
    )

    return {
        "evidence_standard_met": True,
        "evidence_standard_met_reason": (
            f"{noun} submitted for {claim_object} claim; "
            f"structural minimum met per {req_ids_str}.{fallback_note}"
        ),
    }
