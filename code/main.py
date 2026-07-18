"""
Full pipeline entry point: runs every row in dataset/claims.csv through
load_data -> evidence_check -> vision_inspect -> history_risk -> decide
and writes the final predictions to output.csv at the repo root.

Usage (from repo root):
    python code/main.py              # full run
    python code/main.py --limit 3   # dry-run on first N rows only

Checkpointing: if output.csv already exists, rows whose _csv_row index
appears in it are skipped automatically so a re-run after interruption
does not waste API calls on work that already completed.  The checkpoint
key is the 0-based row position in claims.csv, NOT user_id, because
user_id is not unique (the same user can have multiple separate claims).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, "code")

import pandas as pd

from pipeline.load_data import load_claims
from pipeline.process_claim import process_claim

# ── paths ──────────────────────────────────────────────────────────────────────
DATASET_ROOT     = Path("dataset")
CLAIMS_CSV       = DATASET_ROOT / "claims.csv"
HISTORY_CSV      = DATASET_ROOT / "user_history.csv"
REQUIREMENTS_CSV = DATASET_ROOT / "evidence_requirements.csv"
OUTPUT_CSV       = Path("output.csv")

INTER_ROW_DELAY = 5   # seconds between Gemini API calls (free tier ~10 RPM)

# Exact column order required by problem_statement.md
OUTPUT_COLUMNS = [
    "user_id", "image_paths", "user_claim", "claim_object",
    "evidence_standard_met", "evidence_standard_met_reason",
    "risk_flags", "issue_type", "object_part",
    "claim_status", "claim_status_justification",
    "supporting_image_ids", "valid_image", "severity",
]

# Extra columns (not required by problem_statement.md, but tracked for provenance)
EXTRA_COLUMNS = ["model"]


# ── checkpointing helpers ──────────────────────────────────────────────────────
# Checkpoint key: _csv_row (0-based row index in claims.csv).
# user_id is NOT unique — the same user can submit multiple separate claims.

_CSV_ROW_COL = "_csv_row"


def _load_checkpoint() -> tuple[set[int], list[dict]]:
    """Return (done_row_indices, existing_rows) from output.csv, or empty defaults."""
    if not OUTPUT_CSV.exists():
        return set(), []
    try:
        df = pd.read_csv(OUTPUT_CSV, dtype=str).fillna("")
        rows = df.to_dict("records")
        done = {int(r[_CSV_ROW_COL]) for r in rows if r.get(_CSV_ROW_COL, "") != ""}
        return done, rows
    except Exception:
        return set(), []


def _write_output(rows: list[dict]) -> None:
    """Write all rows to output.csv in the required column order.

    The internal _csv_row column is included for checkpointing but is not
    part of the official OUTPUT_COLUMNS required by problem_statement.md.
    The 'model' column tracks which Gemini model processed each claim.
    """
    df = pd.DataFrame(rows)
    out_cols = [c for c in OUTPUT_COLUMNS if c in df.columns]
    extras = [c for c in EXTRA_COLUMNS + [_CSV_ROW_COL] if c in df.columns]
    df[out_cols + extras].to_csv(OUTPUT_CSV, index=False)


# ── main ───────────────────────────────────────────────────────────────────────

def run(limit: int | None = None) -> None:
    print("Loading claims, history, and evidence requirements...")
    claims, _ = load_claims(str(CLAIMS_CSV), str(HISTORY_CSV), str(REQUIREMENTS_CSV))

    if limit is not None:
        claims = claims[:limit]

    total = len(claims)

    done_rows, completed = _load_checkpoint()
    if done_rows:
        print(f"Checkpoint: {len(done_rows)} row(s) already in output.csv — will skip them.")

    errors: list[tuple[str, str]] = []
    valid_false_events: list[tuple[str, str]] = []  # (user_id, claim_object)

    for i, claim in enumerate(claims, start=1):
        uid = claim["user_id"]
        row_idx = i - 1  # 0-based index into claims.csv

        if row_idx in done_rows:
            print(f"[{i:02d}/{total}] {uid} (row {row_idx}) — already done, skipping.")
            continue

        print(f"[{i:02d}/{total}] Processing {uid} ({claim['claim_object']}) "
              f"{claim['image_ids']} ...", end=" ", flush=True)

        made_api_call = bool(claim.get("image_paths"))
        vision_errored = False
        try:
            output = process_claim(claim)
            print("ok" if made_api_call else "skipped (no images)")
            # Log valid_image=False per-row
            if output.get("valid_image") == "false":
                print(f"  [!] valid_image=False  claim_object={claim['claim_object']}")
                valid_false_events.append((uid, claim["claim_object"]))
        except Exception as exc:
            msg = str(exc)
            print(f"FAILED — {msg[:100]}")
            errors.append((uid, msg))
            vision_errored = True
        output[_CSV_ROW_COL] = str(row_idx)

        # Checkpoint only when vision succeeded (or row had no images to inspect).
        # Errored rows are NOT added to done_rows so they are retried on re-run.
        if not vision_errored:
            completed.append(output)
            done_rows.add(row_idx)
            _write_output(completed)

        # Rate-limit courtesy delay — only after rows that made an API call,
        # and only when there are still un-done rows ahead.
        if made_api_call:
            pending = [j for j in range(i, len(claims)) if j not in done_rows]
            if pending:
                time.sleep(INTER_ROW_DELAY)

    succeeded = len(completed) - len(errors)
    print(f"\n{'='*60}")
    print(f"PIPELINE COMPLETE — {len(completed)} rows written to {OUTPUT_CSV}")
    print(f"{'='*60}")
    print(f"  Succeeded:  {succeeded}")
    print(f"  Failed:     {len(errors)}")
    print(f"  vision_result=None (fallback): {len(errors)} rows")
    if errors:
        print(f"\n  Failed rows:")
        for uid, msg in errors:
            print(f"    {uid}: {msg[:120]}")

    # Duplicate user_id pattern check
    print(f"\n  Duplicate user_id pattern check:")
    from collections import Counter
    uid_counts = Counter(r.get("user_id", "") for r in completed)
    dupes = {uid: cnt for uid, cnt in uid_counts.items() if cnt > 1}
    if dupes:
        for uid, cnt in sorted(dupes.items()):
            print(f"    {uid}: appears {cnt}x")
    else:
        print(f"    No duplicates found")

    # valid_image=False events
    print(f"\n  valid_image=False count: {len(valid_false_events)}")
    if valid_false_events:
        vf_by_obj: dict[str, int] = {}
        for uid, obj in valid_false_events:
            vf_by_obj[obj] = vf_by_obj.get(obj, 0) + 1
        for obj, cnt in sorted(vf_by_obj.items()):
            print(f"    {obj}: {cnt}")
        print(f"    Affected users: {', '.join(uid for uid, _ in valid_false_events)}")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the full damage-claim pipeline on dataset/claims.csv"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        metavar="N",
        help="Process only the first N rows (for dry runs)",
    )
    args = parser.parse_args()
    run(limit=args.limit)
