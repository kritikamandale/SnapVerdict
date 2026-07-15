"""
Run vision_inspect on the first 5 rows of sample_claims.csv.
Prints vision output next to expected columns for manual schema verification.

Usage (from repo root):
    python code/pipeline/_test_vision_5rows.py
"""
from __future__ import annotations
import sys
sys.path.insert(0, "code")

import json
from pathlib import Path

import pandas as pd

from pipeline.vision_inspect import inspect_claim_images

DATASET_ROOT = Path("dataset")
SAMPLE_CSV   = DATASET_ROOT / "sample_claims.csv"

# Expected output columns we want to compare
COMPARE_FIELDS = [
    "evidence_standard_met",
    "evidence_standard_met_reason",
    "claim_status",
    "issue_type",
    "object_part",
    "severity",
    "risk_flags",
    "supporting_image_ids",
    "valid_image",
    "claim_status_justification",
]

sample = pd.read_csv(SAMPLE_CSV, dtype=str).fillna("")

for row_num, (_, row) in enumerate(sample.head(5).iterrows(), start=1):
    image_paths_rel = [p.strip() for p in row["image_paths"].split(";") if p.strip()]
    full_paths      = [str(DATASET_ROOT / p) for p in image_paths_rel]
    image_ids       = [Path(p).stem for p in image_paths_rel]

    sep = "=" * 72
    print(f"\n{sep}")
    print(f"ROW {row_num}  {row['user_id']}  ({row['claim_object']})  "
          f"images: {image_ids}")
    print(sep)

    # ---- expected ----
    print("\nEXPECTED (from sample_claims.csv):")
    for field in COMPARE_FIELDS:
        val = row.get(field, "—")
        # Truncate long strings for readability
        display = val if len(val) <= 90 else val[:87] + "..."
        print(f"  {field:<34} {display}")

    # ---- vision ----
    print("\nVISION OUTPUT:")
    try:
        result = inspect_claim_images(row["claim_object"], row["user_claim"], full_paths)

        # Map vision fields to expected field names for side-by-side reading
        vision_display = {
            "evidence_standard_met":        str(result.get("evidence_standard_met_override")),
            "evidence_standard_met_reason": result.get("evidence_standard_met_reason", ""),
            "claim_status":                 result.get("claim_status", ""),
            "issue_type":                   result.get("issue_type", ""),
            "object_part":                  result.get("object_part", ""),
            "severity":                     result.get("severity", ""),
            "risk_flags":                   ";".join(result.get("risk_flags") or []) or "none",
            "supporting_image_ids":         ";".join(result.get("supporting_image_ids") or []) or "none",
            "valid_image":                  str(result.get("valid_image")),
            "claim_status_justification":   result.get("claim_status_justification", ""),
        }
        for field in COMPARE_FIELDS:
            val = vision_display.get(field, "—")
            display = val if len(val) <= 90 else val[:87] + "..."
            match = "+" if val.lower() == row.get(field, "").lower() else " "
            print(f"  {match} {field:<32} {display}")

        print("\n  Raw JSON:")
        print("  " + json.dumps(result, indent=2).replace("\n", "\n  "))

    except Exception as exc:
        print(f"  ERROR: {exc}")
