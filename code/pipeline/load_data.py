from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import pandas as pd


class ClaimRecord(TypedDict):
    # from claims.csv
    user_id: str
    image_paths: list[str]          # split on ";"
    image_ids: list[str]            # stem of each path, e.g. "img_1"
    user_claim: str
    claim_object: str               # car | laptop | package

    # joined from user_history.csv
    past_claim_count: int
    accept_claim: int
    manual_review_claim: int
    rejected_claim: int
    last_90_days_claim_count: int
    history_flags: list[str]        # split on ";", empty list when "none"
    history_summary: str


class EvidenceRequirement(TypedDict):
    requirement_id: str
    claim_object: str               # car | laptop | package | all
    applies_to: str
    minimum_image_evidence: str


_HISTORY_INT_COLS: list[str] = [
    "past_claim_count",
    "accept_claim",
    "manual_review_claim",
    "rejected_claim",
    "last_90_days_claim_count",
]


def _split_semicolon(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def _image_id(path: str) -> str:
    return Path(path).stem


def load_claims(
    claims_csv_path: str,
    user_history_csv_path: str,
    evidence_requirements_csv_path: str,
) -> tuple[list[ClaimRecord], list[EvidenceRequirement]]:
    """Load and join the three input CSVs.

    Returns a (claims, evidence_requirements) pair.  Each claim dict carries
    the raw claim fields, derived image metadata, and the joined history row.
    The evidence_requirements list is returned separately for use in
    evidence_check.py, which applies it per claim based on object type.
    """
    claims_df = pd.read_csv(claims_csv_path, dtype=str).fillna("")
    history_df = pd.read_csv(user_history_csv_path, dtype=str).fillna("")
    req_df = pd.read_csv(evidence_requirements_csv_path, dtype=str).fillna("")

    # Convert integer columns before the merge so fillna(0) is type-safe.
    for col in _HISTORY_INT_COLS:
        history_df[col] = pd.to_numeric(history_df[col], errors="coerce").fillna(0).astype(int)

    merged = claims_df.merge(history_df, on="user_id", how="left")

    # Fill missing history for users not present in user_history.csv.
    for col in _HISTORY_INT_COLS:
        merged[col] = merged[col].fillna(0).astype(int)
    merged["history_flags"] = merged["history_flags"].fillna("none")
    merged["history_summary"] = merged["history_summary"].fillna("")

    claims: list[ClaimRecord] = []
    for _, row in merged.iterrows():
        paths = _split_semicolon(row["image_paths"])

        raw_flags = row["history_flags"]
        flags = (
            []
            if raw_flags.strip().lower() == "none"
            else _split_semicolon(raw_flags)
        )

        record: ClaimRecord = {
            "user_id": row["user_id"],
            "image_paths": paths,
            "image_ids": [_image_id(p) for p in paths],
            "user_claim": row["user_claim"],
            "claim_object": row["claim_object"],
            "past_claim_count": int(row["past_claim_count"]),
            "accept_claim": int(row["accept_claim"]),
            "manual_review_claim": int(row["manual_review_claim"]),
            "rejected_claim": int(row["rejected_claim"]),
            "last_90_days_claim_count": int(row["last_90_days_claim_count"]),
            "history_flags": flags,
            "history_summary": row["history_summary"],
        }
        claims.append(record)

    evidence_requirements: list[EvidenceRequirement] = [
        {
            "requirement_id": row["requirement_id"],
            "claim_object": row["claim_object"],
            "applies_to": row["applies_to"],
            "minimum_image_evidence": row["minimum_image_evidence"],
        }
        for _, row in req_df.iterrows()
    ]

    return claims, evidence_requirements
