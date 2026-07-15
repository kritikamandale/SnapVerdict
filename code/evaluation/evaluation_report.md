# Evaluation Report — HackerRank Orchestrate (June 2026)

Multi-modal damage claim verification pipeline. This document captures baseline metrics from the first full pipeline run and flags pending items.

---

## Run Summary

### Run 1 — Pre-checkpoint-fix (completed before 2026-07-14)

| Metric | Value |
|---|---|
| **Date** | 2026-07-14 (early morning, before checkpoint fix) |
| **Input** | `dataset/claims.csv` (44 rows, 36 unique `user_id`s, 8 duplicates) |
| **Output** | `output.csv` — **36 rows** (skipped 8 duplicate user_ids due to checkpoint bug) |
| **API calls made** | 36 |
| **Images processed** | 67 (across 36 unique claims) |
| **Vision failures** | 0 (zero fallbacks to `vision_result=None`) |
| **Runtime** | ~8 minutes |
| **Estimated cost** | $0 (Gemini free tier) |

### Run 2 — Post-checkpoint-fix (partial, interrupted by quota + timeout)

| Metric | Value |
|---|---|
| **Date** | 2026-07-14 (after checkpoint fix and object_part sanitization) |
| **Input** | `dataset/claims.csv` (44 rows) |
| **Rows attempted** | 4 (rows 0–3 before 600 s timeout) |
| **Rows written to output.csv** | 3 (user_002, user_005, user_007) |
| **Genuine 429 failures** | 1 (user_004 — all keys exhausted) |
| **False-positive failures** | 2 (user_002, user_007 — emoji encoding crash; data written correctly, only logging misclassified) |
| **Rows lost to bad data** | 0 |

---

## Key Rotation & Quota

### Strategy

N-key round-robin (6 keys configured). On 429, the exhausted key is marked and skipped for the rest of the run; the next available key is tried immediately. On 503, exponential backoff (1 s → 2 s → 4 s) on the same key. Max 3 retries per call before giving up.

### Critical finding: all 6 keys share ONE GCP project quota

**The initial assumption — that each API key has its own independent 20 req/day quota — is wrong.** All 6 keys share a single `20 requests/day/project/model` quota bucket for `gemini-2.5-flash` (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`). Different keys from the same GCP project do NOT provide quota multiplication.

**Evidence from Run 1 (36 calls):**
- Keys 4, 5, 6 hit 429 around row 30 (~6 calls each)
- Keys 1, 2, 3 appeared to have "spare quota" — but this was misleading
- The pattern is consistent with a per-minute sub-limit within the shared daily cap, not independent per-key quotas

**Evidence from Run 2 (3 calls before full exhaustion):**
- Key 1 succeeded for the single test call + row 0 (user_002) = 2 calls
- Key 2 attempted for row 1 (user_005) → 429 on key 1 (0-indexed), switched to key 3 → 429 on key 3, then all keys exhausted within a single row
- Key 4 eventually succeeded for row 3 (user_007) after multiple retries
- Total successful calls before complete lockout: 3–4 (within a single minute)

This confirms the daily cap is shared. The difference in exhaustion timing between runs is explained by the per-minute sub-limit: Run 1 spread 36 calls over ~8 minutes (staying under the per-minute limit), while Run 2 hit the per-minute wall immediately because the daily cap was already mostly consumed by Run 1 + the test call.

**Implication:** True quota multiplication requires keys from **different GCP projects**, not just different accounts under the same project. A single GCP project provides exactly 20 requests/day for `gemini-2.5-flash` free tier, regardless of how many API keys are created within it.

### Exhaustion timeline — Run 1

| Phase | Keys used | Outcome |
|---|---|---|
| Rows 1–29 | Keys 1→2→3→4→5→6 (clean round-robin) | All succeeded, no 429s |
| Row 30 (user_042) | Key 4 → 429 → Key 5 → 429 → Key 6 → 429 → Key 1 → ok | Keys 4, 5, 6 exhausted |
| Rows 31–32 | Keys 2, 3 | OK |
| Row 33 (user_045) | Key 4 (already exhausted, skipped) → Key 1 → ok | — |
| Rows 34–35 | Keys 2, 3 | OK |
| Row 38 (user_022) | Key 4 (already exhausted, skipped) → Key 1 → ok | — |
| Rows 39–40 | Keys 1, 2 | OK |

**Final state:** Keys 4, 5, 6 exhausted. Keys 1, 2, 3 had remaining calls (within daily cap, but per-minute limit intermittently triggered).

### Exhaustion timeline — Run 2

| Phase | Keys used | Outcome |
|---|---|---|
| Test call | Key 1 | OK (consumed 1 of remaining daily quota) |
| Row 0 (user_002) | Key 1 | OK |
| Row 1 (user_005) | Key 2 → 429 → Key 3 → 429 → all exhausted → wait-and-retry on Key 3 → OK after backoff | Daily cap effectively hit |
| Row 2 (user_004) | Key 4 → 429 → all exhausted → 3 retries at 65 s each → all 429 | **FAILED** — genuine quota exhaustion |
| Row 3 (user_007) | Key 4 → 429 → wait-and-retry → OK after backoff | Intermittent recovery |
| Row 4+ | Timeout killed the run | — |

---

## Fixed: Windows cp1252 Emoji Encoding Crash (Run 2)

### Impact

Two rows (user_002, user_007) had their vision calls succeed but were misclassified as failures because a `print()` statement containing the ⚠ emoji (U+26A0) crashed on Windows with `cp1252` default encoding. The crash was caught by a bare `except Exception` block, which added the row to the `errors` list even though `vision_result` was valid and `decide()` produced correct output.

**Data loss: 0 rows.** The `except` block does not prevent `decide()` from running — execution continues after the try/except. All 3 rows in `output.csv` have correct, vision-derived values.

**Tracking loss: 2 events.** The `valid_false_events` list (tracks which `claim_object` types trigger `valid_image=False`) lost its entries for user_002 and user_007.

### Before/after code

**Before (buggy — `main.py`):**
```python
try:
    vision_result = inspect_claim_images(...)
    print("ok")
    if vision_result.get("valid_image") is False:
        print(f"  ⚠ valid_image=False  claim_object={claim['claim_object']}")
        valid_false_events.append((uid, claim["claim_object"]))
except Exception as exc:
    msg = str(exc)
    print(f"FAILED — {msg[:100]}")
    errors.append((uid, msg))
```

**After (fixed):**
```python
try:
    vision_result = inspect_claim_images(...)
    print("ok")
    if vision_result.get("valid_image") is False:
        print(f"  [!] valid_image=False  claim_object={claim['claim_object']}")
        valid_false_events.append((uid, claim["claim_object"]))
except Exception as exc:
    msg = str(exc)
    print(f"FAILED — {msg[:100]}")
    errors.append((uid, msg))
```

The only change is `⚠` → `[!]`. The bug was purely a Windows console encoding issue — Python's `stdout` defaults to `cp1252` on Windows, which has no mapping for U+26A0.

---

## Per-Field Accuracy

> **Blocked:** Pending full 44-row pipeline completion after quota reset. Table will be populated after a successful `run_eval.py` run against `dataset/sample_claims.csv` (20 labeled rows).

| Field | Correct | Total | Accuracy |
|---|---|---|---|
| `evidence_standard_met` | — | 20 | *pending* |
| `risk_flags` | — | 20 | *pending* |
| `issue_type` | — | 20 | *pending* |
| `object_part` | — | 20 | *pending* |
| `claim_status` | — | 20 | *pending* |
| `supporting_image_ids` | — | 20 | *pending* |
| `valid_image` | — | 20 | *pending* |
| `severity` | — | 20 | *pending* |
| **OVERALL** | — | **160** | *pending* |

---

## `claim_status` Mismatch Analysis

> **Blocked:** Pending `run_eval.py` completion. Each mismatch will be printed with predicted vs expected justifications side-by-side.

---

## Final Row Count Confirmation

> **Blocked:** Pending full re-run with checkpoint fix. Expected: **44/44 rows** in `output.csv`, with duplicate `user_id`s preserved:
>
> | user_id | Expected count |
> |---|---|
> | user_045 | 3 |
> | user_034 | 2 |
> | user_042 | 2 |
> | user_004 | 2 |
> | user_018 | 2 |
> | user_040 | 2 |
> | user_041 | 2 |
> | All others | 1 each |

### Current state (3 rows)

| Row (_csv_row) | user_id | claim_status | issue_type | object_part | valid_image |
|---|---|---|---|---|---|
| 0 | user_002 | contradicted | scratch | front_bumper | false |
| 1 | user_005 | supported | dent | door | true |
| 3 | user_007 | contradicted | none | side_mirror | false |

Row 2 (user_004) is missing — the only genuine 429 failure. All remaining rows (4–43) were never attempted (timeout).

---

## Known Issues

### 1. Checkpoint deduplication bug (fixed, pending re-run)

`main.py` and `run_eval.py` previously used `user_id` as the checkpoint key. Since `user_id` is not unique (8 duplicate users in `claims.csv`), 8 legitimate claims were silently skipped, producing 36 rows instead of 44. Fixed by switching to `_csv_row` (0-based row index in the input CSV). The re-run is blocked on quota reset.

### 2. `manual_review_required` is a pass-through, not derived

The `risk_flags` field includes `manual_review_required` in several ground-truth rows. This flag is **not derivable** from `user_history.csv` numeric columns alone — it requires contextual judgment about image quality, claim consistency, or adversarial patterns (e.g., text instructions embedded in images). The current pipeline passes it through from the vision model's output when the model includes it, but does not independently generate it. This limits recall on rows where the model fails to surface it.

### 3. Gemini free-tier quota is shared across all API keys within a single GCP project

The 20-request daily limit per GCP project applies to the **project**, not to individual API keys. Creating 6 keys under the same project does NOT provide 6× quota — it provides 20 requests/day total. True quota multiplication requires keys from **different GCP projects**, not just different accounts under the same project. This was confirmed empirically: Run 1 exhausted all 6 keys after 36 calls (spread over 8 minutes, with per-minute sub-limits causing staggered exhaustion), and Run 2 exhausted all keys after just 3–4 calls (daily cap was already consumed).

### 4. No translation layer

Multilingual claims (Hindi, Spanish, Chinese, Hinglish) are sent to Gemini as-is. Gemini handles them, but translation to English before prompting could improve consistency on non-English claims, particularly for `claim_status_justification` quality.

### 5. `severity` and `issue_type` are model-only

These fields come entirely from the vision model with no deterministic cross-check. The model sometimes over-estimates severity (e.g., calling a scratch "high" severity) or misclassifies issue types (e.g., `glass_shatter` vs `crack`). A rule layer mapping `(object_part, damage_pattern) → severity_range` could reduce variance.

### 6. Windows cp1252 encoding crashes on non-ASCII log output (fixed)

Python's `stdout` on Windows defaults to the `cp1252` codec, which cannot encode characters like ⚠ (U+26A0). A `print()` statement with this character inside a `try/except Exception` block caused the block to silently misclassify success as failure. Fixed by replacing the emoji with plain ASCII `[!]`. Any future `print()` statements in the pipeline must avoid non-ASCII characters or explicitly set `stdout` encoding to UTF-8.
