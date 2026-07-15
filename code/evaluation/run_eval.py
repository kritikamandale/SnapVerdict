"""
Full-pipeline evaluation against dataset/sample_claims.csv.

Runs load_data → evidence_check → vision_inspect → history_risk → decide
for every row, compares predicted output to ground-truth columns field by
field, and reports per-field accuracy plus every claim_status mismatch.

Usage (from repo root):
    python code/evaluation/run_eval.py

Outputs:
    stdout  — per-field accuracy table + claim_status mismatch details
    file    — dataset/eval_output_tmp.csv  (full 20-row predicted output)

Checkpointing uses _csv_row (0-based row index) as the key, NOT user_id,
because user_id is not unique — the same user can have multiple claims.
"""
from __future__ import annotations

import sys
sys.path.insert(0, "code")

import time
from pathlib import Path

import pandas as pd

from pipeline.load_data import load_claims
from pipeline.evidence_check import check_evidence_sufficiency
from pipeline.vision_inspect import inspect_claim_images
from pipeline.decide import decide, FinalOutput

# ── paths ──────────────────────────────────────────────────────────────────────
DATASET_ROOT      = Path("dataset")
SAMPLE_CSV        = DATASET_ROOT / "sample_claims.csv"
HISTORY_CSV       = DATASET_ROOT / "user_history.csv"
REQUIREMENTS_CSV  = DATASET_ROOT / "evidence_requirements.csv"
TMP_OUTPUT_CSV    = DATASET_ROOT / "eval_output_tmp.csv"

INTER_ROW_DELAY = 5   # seconds between Gemini calls (Gemini free tier: ~10 RPM)

# ── checkpointing helpers ──────────────────────────────────────────────────────
_CSV_ROW_COL = "_csv_row"


def _load_eval_checkpoint() -> tuple[set[int], list[dict]]:
    """Return (done_row_indices, existing_rows) from TMP_OUTPUT_CSV, or empty defaults."""
    if not TMP_OUTPUT_CSV.exists():
        return set(), []
    try:
        df = pd.read_csv(TMP_OUTPUT_CSV, dtype=str).fillna("")
        rows = df.to_dict("records")
        done = {int(r[_CSV_ROW_COL]) for r in rows if r.get(_CSV_ROW_COL, "") != ""}
        return done, rows
    except Exception:
        return set(), []


# ── evaluation config ──────────────────────────────────────────────────────────
EVAL_FIELDS = [
    "evidence_standard_met",
    "risk_flags",
    "issue_type",
    "object_part",
    "claim_status",
    "supporting_image_ids",
    "valid_image",
    "severity",
]
SET_FIELDS = {"risk_flags", "supporting_image_ids"}


# ── comparison helpers ─────────────────────────────────────────────────────────

def _to_set(raw: str) -> set[str]:
    raw = raw.strip().lower()
    if raw in ("", "none"):
        return set()
    return {p.strip() for p in raw.split(";") if p.strip()}


def _field_match(field: str, predicted: str, expected: str) -> bool:
    if field in SET_FIELDS:
        return _to_set(predicted) == _to_set(expected)
    return predicted.strip().lower() == expected.strip().lower()


# ── main ───────────────────────────────────────────────────────────────────────

def run_eval() -> None:
    print("Loading claims and evidence requirements...")
    claims, _ = load_claims(str(SAMPLE_CSV), str(HISTORY_CSV), str(REQUIREMENTS_CSV))
    evidence_df = pd.read_csv(str(REQUIREMENTS_CSV), dtype=str).fillna("")

    ground_truth = pd.read_csv(SAMPLE_CSV, dtype=str).fillna("").set_index("user_id")
    done_rows, results = _load_eval_checkpoint()
    if done_rows:
        print(f"Checkpoint: {len(done_rows)} row(s) already in eval_output_tmp.csv — skipping them.")
    print(f"Loaded {len(claims)} claims. Running full pipeline...\n")

    errors: list[tuple[str, str]] = []

    for i, claim in enumerate(claims, start=1):
        uid = claim["user_id"]
        row_idx = i - 1  # 0-based index into sample_claims.csv

        if row_idx in done_rows:
            print(f"[{i:02d}/{len(claims)}] {uid} (row {row_idx}) — already done, skipping.")
            continue

        print(f"[{i:02d}/{len(claims)}] {uid}  ({claim['claim_object']})  "
              f"{claim['image_ids']} ...", end=" ", flush=True)

        # Stage 1: structural evidence gate
        ev_result = check_evidence_sufficiency(
            claim["claim_object"], claim["image_paths"], evidence_df
        )

        # Stage 2: vision (skip only if no images submitted)
        vision_result = None
        made_api_call = False
        if claim["image_paths"]:
            full_paths = [str(DATASET_ROOT / p) for p in claim["image_paths"]]
            made_api_call = True
            try:
                vision_result = inspect_claim_images(
                    claim["claim_object"], claim["user_claim"], full_paths
                )
                print("ok")
            except Exception as exc:
                msg = str(exc)
                print(f"ERROR — {msg[:80]}")
                errors.append((uid, msg))
        else:
            print("skipped (no images)")

        # Stage 3: merge into final output (decide handles vision_result=None)
        output = decide(claim, ev_result, vision_result)
        output[_CSV_ROW_COL] = str(row_idx)

        # Checkpoint only when vision succeeded (or row had no images).
        # Errored rows stay out of done_rows so they are retried on re-run.
        vision_errored = made_api_call and vision_result is None
        if not vision_errored:
            results.append(output)
            done_rows.add(row_idx)
            pd.DataFrame(results).to_csv(TMP_OUTPUT_CSV, index=False)

        if made_api_call:
            pending = [j for j in range(i, len(claims)) if j not in done_rows]
            if pending:
                time.sleep(INTER_ROW_DELAY)

    print(f"\nDone. {len(results) - len(errors)} succeeded, {len(errors)} errored.\n")
    print(f"Predicted output -> {TMP_OUTPUT_CSV}\n")

    # ── accuracy table ─────────────────────────────────────────────────────────
    field_correct: dict[str, int] = {f: 0 for f in EVAL_FIELDS}
    field_total:   dict[str, int] = {f: 0 for f in EVAL_FIELDS}
    errored_uids = {uid for uid, _ in errors}
    claim_status_mismatches: list[dict] = []

    for output in results:
        uid = output["user_id"]
        if uid in errored_uids or uid not in ground_truth.index:
            continue
        gt = ground_truth.loc[uid]

        for field in EVAL_FIELDS:
            pred = str(output.get(field, ""))
            exp  = str(gt.get(field, ""))
            field_total[field] += 1
            if _field_match(field, pred, exp):
                field_correct[field] += 1
            elif field == "claim_status":
                claim_status_mismatches.append({
                    "user_id":               uid,
                    "predicted":             pred,
                    "expected":              exp,
                    "pred_justification":    output.get("claim_status_justification", ""),
                    "exp_justification":     str(gt.get("claim_status_justification", "")),
                })

    total_comparisons = sum(field_total.values())
    total_correct     = sum(field_correct.values())

    print("=" * 64)
    print("PER-FIELD ACCURACY")
    print("=" * 64)
    for field in EVAL_FIELDS:
        n   = field_total[field]
        ok  = field_correct[field]
        pct = 100 * ok / n if n else 0.0
        bar = "+" * ok + "." * (n - ok)
        print(f"  {field:<28} {ok:>2}/{n}  [{bar:<20}]  {pct:5.1f}%")

    overall_pct = 100 * total_correct / total_comparisons if total_comparisons else 0.0
    print(f"\n  {'OVERALL':<28} {total_correct:>3}/{total_comparisons}"
          f"  {overall_pct:.1f}%")
    if errored_uids:
        print(f"\n  (excluded from accuracy: {sorted(errored_uids)})")

    # ── claim_status mismatches ────────────────────────────────────────────────
    sep = "=" * 64
    print(f"\n{sep}")
    print(f"CLAIM_STATUS MISMATCHES  ({len(claim_status_mismatches)} disagreements)")
    print(sep)

    if not claim_status_mismatches:
        print("  None — every claim_status matched ground truth.\n")
    else:
        for m in claim_status_mismatches:
            print(f"\n  user_id   : {m['user_id']}")
            print(f"  predicted : {m['predicted']}")
            print(f"  expected  : {m['expected']}")
            print(f"  pred why  : {m['pred_justification']}")
            print(f"  exp  why  : {m['exp_justification']}")

    # ── errors ─────────────────────────────────────────────────────────────────
    if errors:
        print(f"\n{sep}")
        print(f"VISION ERRORS  ({len(errors)})")
        print(sep)
        for uid, msg in errors:
            print(f"  {uid}: {msg[:120]}")


if __name__ == "__main__":
    run_eval()
