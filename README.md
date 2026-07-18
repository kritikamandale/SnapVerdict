# Code — Multi-Modal Damage Claim Verification

Multi-modal evidence review system for the HackerRank Orchestrate (June 2026) hackathon. Verifies visual evidence for damage claims across **cars**, **laptops**, and **packages** using Google Gemini's vision API.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env and fill in real API keys
```

## Environment Variables

All variables are set in a `.env` file at the repo root (see `.env.example`). None are hardcoded.

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY_1` | **Yes** (at least one) | Gemini API key (Google AI Studio) |
| `GEMINI_API_KEY_2` | Optional | Second Gemini key |
| `GEMINI_API_KEY_3` | Optional | Third Gemini key |
| `GEMINI_API_KEY_4` | Optional | Fourth Gemini key |
| `GEMINI_API_KEY_5` | Optional | Fifth Gemini key |
| `GEMINI_API_KEY_6` | Optional | Sixth Gemini key |
| `VISION_BACKEND` | Optional | Reserved for future multi-backend support (currently Gemini only) |

Keys are rotated round-robin. Exhausted keys (429) are skipped automatically for the rest of the run. **All keys from the same GCP project share a single 20 req/day quota bucket** — true quota multiplication requires keys from different GCP projects, not just different accounts under the same project.

## Running the Pipeline

```bash
# Full run — processes dataset/claims.csv, writes output.csv
python code/main.py

# Dry run — process only the first N rows
python code/main.py --limit 5
```

## Running Evaluation

```bash
# Full evaluation against dataset/sample_claims.csv (20 labeled rows)
python code/evaluation/run_eval.py
```

Produces per-field accuracy percentages and logs every `claim_status` mismatch with side-by-side justifications. Writes temporary predictions to `dataset/eval_output_tmp.csv`.

## Running the API

```bash
# Start the FastAPI server (from repo root)
uvicorn --app-dir code api.main:app --reload --port 8000
```

### Endpoints

**GET /health** — uptime check

```json
{"status": "ok"}
```

**POST /claims** — submit a single damage claim with images

| Field | Type | Required |
|---|---|---|
| `images` | file(s) | Yes — one or more image files |
| `user_claim` | text | Yes — the claim description |
| `claim_object` | text | Yes — `car`, `laptop`, or `package` |

**Example (curl):**

```bash
curl -X POST http://localhost:8000/claims \
  -F "images=@dataset/images/sample/case_001/img_1.jpg" \
  -F "user_claim=Scratch on the front bumper" \
  -F "claim_object=car"
```

**Success response:**

```json
{
  "evidence_standard_met": "true",
  "evidence_standard_met_reason": "1 image submitted for car claim ...",
  "risk_flags": "none",
  "issue_type": "scratch",
  "object_part": "front_bumper",
  "claim_status": "supported",
  "claim_status_justification": "img_1 shows a visible scratch ...",
  "supporting_image_ids": "img_1",
  "valid_image": "true",
  "severity": "low",
  "model": "gemini-2.5-flash"
}
```

**Validation error:**

```json
{
  "error": true,
  "error_message": "claim_object 'bike' is not allowed. Must be one of: car, laptop, package."
}
```

**Quota exhausted:**

```json
{
  "error": true,
  "error_type": "quota_exhausted",
  "error_message": "Demo is at daily API capacity — please try again later."
}
```

## Pipeline Architecture

Five stages, each in its own module under `code/pipeline/`:

| # | Stage | Module | What it does |
|---|---|---|---|
| 1 | **load_data** | `load_data.py` | Reads `claims.csv`, `user_history.csv`, `evidence_requirements.csv`; joins claim records with user history |
| 2 | **evidence_check** | `evidence_check.py` | Deterministic gate — checks whether enough images were submitted per the evidence requirements table |
| 3 | **vision_inspect** | `vision_inspect.py` | Sends images + claim text to Gemini 2.5 Flash; returns structured JSON with damage assessment; sanitizes `object_part` against allowed-value lists (strips prefixes, normalizes spaces to underscores) |
| 4 | **history_risk** | `history_risk.py` | Extracts risk flags from `user_history.csv` for each user (claim frequency, prior rejections) |
| 5 | **decide** | `decide.py` | Merges evidence check + vision result + history flags into the final output row |

## Checkpointing

Both `main.py` and `run_eval.py` write results incrementally. On re-run, completed rows are detected by their `_csv_row` index (0-based position in the input CSV) and skipped automatically. Interrupted runs resume from where they left off — no work is duplicated.

Failed rows (vision API errors after all retries) are **not** checkpointed and will be retried on the next run.

## Known Limitations

See `evaluation_report.md` for full details. Summary:

- Gemini free tier limits to 20 requests/day/project/model — all keys from the same GCP project share this cap; true multiplication requires separate GCP projects
- `claim_status` accuracy varies; model sometimes over-interprets image severity
- No translation layer — multilingual claims (Hindi, Spanish, Chinese) are sent to Gemini as-is
- `risk_flags` from history are passed through but not escalated by the pipeline
- `object_part` requires post-API sanitization (the model prepends claim_object names like "car door" instead of "door")
