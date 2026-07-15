from __future__ import annotations

from typing import TypedDict

from pipeline.load_data import ClaimRecord
from pipeline.evidence_check import EvidenceSufficiencyResult
from pipeline.vision_inspect import VisionResult
from pipeline.history_risk import extract_history_flags


class FinalOutput(TypedDict):
    user_id: str
    image_paths: str
    user_claim: str
    claim_object: str
    evidence_standard_met: str
    evidence_standard_met_reason: str
    risk_flags: str
    issue_type: str
    object_part: str
    claim_status: str
    claim_status_justification: str
    supporting_image_ids: str
    valid_image: str
    severity: str


def _join_flags(flags: list[str]) -> str:
    return ";".join(flags) if flags else "none"


def _join_ids(ids: list[str]) -> str:
    return ";".join(ids) if ids else "none"


def decide(
    claim: ClaimRecord,
    evidence_result: EvidenceSufficiencyResult,
    vision_result: VisionResult | None,
) -> FinalOutput:
    """Merge all pipeline stages into a single output row.

    vision_result is None when evidence_check failed structurally (zero
    images) or when the vision call errored — in both cases we fall back
    to evidence_check's verdict and fill safe defaults for vision fields.

    Risk-flag merging order:
      1. Vision flags (order preserved from model output)
      2. History flags not already present (deduped)
    """
    history_flags = extract_history_flags(claim)
    img_paths_str = ";".join(claim.get("image_paths", []))

    if vision_result is None:
        return {
            "user_id": claim["user_id"],
            "image_paths": img_paths_str,
            "user_claim": claim["user_claim"],
            "claim_object": claim["claim_object"],
            "evidence_standard_met": "false",
            "evidence_standard_met_reason": evidence_result["evidence_standard_met_reason"],
            "risk_flags": _join_flags(history_flags),
            "issue_type": "unknown",
            "object_part": "unknown",
            "claim_status": "not_enough_information",
            "claim_status_justification": "",
            "supporting_image_ids": "none",
            "valid_image": "true",
            "severity": "unknown",
        }

    # Merge: vision flags first, then any history flags not already present
    vision_flags: list[str] = list(vision_result.get("risk_flags") or [])
    seen = set(vision_flags)
    for f in history_flags:
        if f not in seen:
            vision_flags.append(f)
            seen.add(f)

    supporting = list(vision_result.get("supporting_image_ids") or [])

    return {
        "user_id": claim["user_id"],
        "image_paths": img_paths_str,
        "user_claim": claim["user_claim"],
        "claim_object": claim["claim_object"],
        "evidence_standard_met": "true" if vision_result["evidence_standard_met_override"] else "false",
        "evidence_standard_met_reason": vision_result.get("evidence_standard_met_reason", ""),
        "risk_flags": _join_flags(vision_flags),
        "issue_type": vision_result.get("issue_type") or "unknown",
        "object_part": vision_result.get("object_part") or "unknown",
        "claim_status": vision_result.get("claim_status") or "not_enough_information",
        "claim_status_justification": vision_result.get("claim_status_justification", ""),
        "supporting_image_ids": _join_ids(supporting),
        "valid_image": "true" if vision_result.get("valid_image") else "false",
        "severity": vision_result.get("severity") or "unknown",
    }
