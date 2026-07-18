"""
Single-claim processing function.

Runs one claim through evidence_check -> vision_inspect -> decide.
Designed to be called from both the batch CSV runner (main.py) and a
future single-claim API endpoint.

The evidence requirements DataFrame is lazy-loaded on first call and
cached for the process lifetime.  Image paths in the claim dict are
resolved relative to the dataset root.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from PIL import Image

from pipeline.evidence_check import check_evidence_sufficiency
from pipeline.vision_inspect import inspect_claim_images
from pipeline.decide import decide

_DATASET_ROOT = Path("dataset")
_evidence_df: pd.DataFrame | None = None

ALLOWED_CLAIM_OBJECTS: set[str] = {"car", "laptop", "package"}
_MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


def _get_evidence_df() -> pd.DataFrame:
    """Lazy-load and cache the evidence requirements DataFrame."""
    global _evidence_df
    if _evidence_df is None:
        _evidence_df = pd.read_csv(
            str(_DATASET_ROOT / "evidence_requirements.csv"), dtype=str
        ).fillna("")
    return _evidence_df


def _validate_claim(claim: dict) -> str | None:
    """Return an error message if the claim dict fails basic validation, else None."""
    # claim_object
    claim_object = (claim.get("claim_object") or "").strip().lower()
    if not claim_object:
        return "claim_object is required but was empty or missing."
    if claim_object not in ALLOWED_CLAIM_OBJECTS:
        return (
            f"claim_object '{claim_object}' is not allowed. "
            f"Must be one of: {', '.join(sorted(ALLOWED_CLAIM_OBJECTS))}."
        )

    # user_claim
    user_claim = (claim.get("user_claim") or "").strip()
    if not user_claim:
        return "user_claim is required but was empty or missing."

    # image_paths
    image_paths = claim.get("image_paths") or []
    if not image_paths:
        return "image_paths is required but was empty or missing."

    for rel_path in image_paths:
        full = _DATASET_ROOT / rel_path
        if not full.exists():
            return f"Image file not found: {rel_path}"
        if full.stat().st_size > _MAX_IMAGE_BYTES:
            mb = full.stat().st_size / (1024 * 1024)
            return f"Image '{rel_path}' is {mb:.1f} MB, exceeding the 10 MB limit."
        try:
            with Image.open(full) as img:
                img.verify()
        except Exception:
            return f"Image '{rel_path}' is corrupt or not a valid image file."

    return None


def _error_result(message: str) -> dict:
    """Return a structured error result matching the output shape."""
    return {
        "error": True,
        "error_message": message,
        "evidence_standard_met": "false",
        "evidence_standard_met_reason": "",
        "risk_flags": "none",
        "issue_type": "unknown",
        "object_part": "unknown",
        "claim_status": "not_enough_information",
        "claim_status_justification": "",
        "supporting_image_ids": "none",
        "valid_image": "true",
        "severity": "unknown",
    }


def process_claim(claim: dict) -> dict:
    """
    Runs one claim through evidence_check -> vision_inspect -> decide.

    ``claim`` must have:
      - claim_object (str)
      - image_paths  (list of str, relative to dataset/)
      - user_claim   (str)

    Optional:
      - user_id (str | None — empty or absent for anonymous)
      - Any user_history fields (history_flags, past_claim_count, etc.)
        — if absent, history_risk.py treats them as no risk contribution.

    Returns the same output dict structure as ``decide()`` produces,
    or an error dict (with ``error: True``) on validation failure.

    Raises on Gemini API errors — the caller is responsible for
    try/except and error logging (as in main.py's batch loop).
    """
    # Input validation
    error = _validate_claim(claim)
    if error is not None:
        return _error_result(error)

    # Stage 1: deterministic evidence gate
    evidence_df = _get_evidence_df()
    ev_result = check_evidence_sufficiency(
        claim["claim_object"], claim["image_paths"], evidence_df
    )

    # Stage 2: vision inspection (skipped when no images)
    vision_result = None
    if claim.get("image_paths"):
        full_paths = [str(_DATASET_ROOT / p) for p in claim["image_paths"]]
        vision_result = inspect_claim_images(
            claim["claim_object"], claim["user_claim"], full_paths
        )

    # Stage 3: merge all stages into final output row
    return decide(claim, ev_result, vision_result)
