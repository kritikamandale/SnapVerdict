"""
Minimal test: exactly 3 Gemini API calls — one per GCP project, one row each.
Project 1 (key 1)  → gemini-2.5-flash
Project 2 (key 7)  → gemini-2.0-flash
Project 3 (key 8)  → gemini-2.0-flash
"""
from __future__ import annotations

import os, sys, time
from pathlib import Path

sys.path.insert(0, "code")

from dotenv import load_dotenv
load_dotenv()

import google.genai as genai
from google.genai import errors as genai_errors
from google.genai import types

from config.prompts import SYSTEM_PROMPT, build_user_prompt

# ── Test rows (one per project) ──────────────────────────────────────────────
# Using sample_claims.csv rows; pick a car, a laptop, and a package.
TEST_ROWS = [
    {
        "project": "gen-lang-client-0765394622",
        "env_key": "GEMINI_API_KEY_1",
        "key_num": 1,
        "model": "gemini-2.5-flash",
        "claim_object": "car",
        "user_claim": "Customer: Hi, I found new damage on my car after it was parked overnight. | Support: Can you describe what changed? | Customer: The back of the car has a dent now. It was not there before. | Support: Did anything else break or is it mostly body damage? | Customer: Mostly the rear bumper area.",
        "image_paths": ["dataset/images/sample/case_001/img_1.jpg"],
    },
    {
        "project": "rankproject-502415",
        "env_key": "GEMINI_API_KEY_7",
        "key_num": 7,
        "model": "gemini-2.0-flash",
        "claim_object": "laptop",
        "user_claim": "Customer: My laptop fell from the table yesterday. | Support: Is it turning on? | Customer: It turns on, but the display glass has a crack now. | Support: Are you reporting the screen only or the whole laptop? | Customer: The screen is the issue.",
        "image_paths": ["dataset/images/sample/case_009/img_1.jpg"],
    },
    {
        "project": "ambient-sphere-502415-a7",
        "env_key": "GEMINI_API_KEY_8",
        "key_num": 8,
        "model": "gemini-2.0-flash",
        "claim_object": "package",
        "user_claim": "Customer: My delivery box arrived damaged. | Support: What part of the package was affected? | Customer: One corner was crushed in when I received it. | Support: Is the item inside part of this claim? | Customer: Not right now. I am reporting the package corner damage.",
        "image_paths": ["dataset/images/sample/case_015/img_1.jpg"],
    },
]

# ── Helpers ──────────────────────────────────────────────────────────────────
_MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}

def load_image(path: str) -> tuple[bytes, str]:
    ext = Path(path).suffix.lower()
    with open(path, "rb") as fh:
        return fh.read(), _MEDIA_TYPES.get(ext, "image/jpeg")

def parse_json(raw: str) -> dict:
    import json
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        body = [l for l in lines[1:] if l.strip() != "```"]
        text = "\n".join(body).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end+1])
    raise ValueError(f"Could not extract JSON: {text[:200]!r}")

# ── Run 3 test calls ─────────────────────────────────────────────────────────
results: list[dict] = []

for i, row in enumerate(TEST_ROWS, 1):
    api_key = os.environ.get(row["env_key"], "").strip()
    print(f"\n{'='*60}")
    print(f"CALL {i}/3 — project={row['project']}  key={row['key_num']}  model={row['model']}")
    print(f"  claim_object={row['claim_object']}  images={len(row['image_paths'])}")
    print(f"  api_key present: {'YES' if api_key else 'NO (MISSING!)'}")

    if not api_key:
        results.append({"project": row["project"], "success": False, "error": "API key not found in env"})
        continue

    # Build content parts
    image_ids = [Path(p).stem for p in row["image_paths"]]
    parts: list[types.Part] = [
        types.Part.from_text(text=build_user_prompt(row["claim_object"], row["user_claim"], image_ids))
    ]
    for path, img_id in zip(row["image_paths"], image_ids):
        raw_bytes, media_type = load_image(path)
        parts.append(types.Part.from_text(text=f"[{img_id}]"))
        parts.append(types.Part.from_bytes(data=raw_bytes, mime_type=media_type))
    parts.append(types.Part.from_text(text="Return only the JSON object:"))

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
    )

    t0 = time.time()
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=row["model"],
            contents=parts,
            config=config,
        )
        elapsed = time.time() - t0
        parsed = parse_json(response.text)
        print(f"  [OK] SUCCESS in {elapsed:.1f}s")
        print(f"  claim_status     = {parsed.get('claim_status')}")
        print(f"  issue_type       = {parsed.get('issue_type')}")
        print(f"  object_part      = {parsed.get('object_part')}")
        print(f"  severity         = {parsed.get('severity')}")
        print(f"  valid_image      = {parsed.get('valid_image')}")
        results.append({"project": row["project"], "success": True, "elapsed": elapsed, "parsed": parsed})
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"  [FAIL] FAILED in {elapsed:.1f}s -- {type(exc).__name__}: {str(exc)[:200]}")
        results.append({"project": row["project"], "success": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})

    if i < len(TEST_ROWS):
        time.sleep(2)

# ── Summary ──────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")
any_success = False
for r in results:
    status = "[OK] PASS" if r["success"] else "[FAIL] FAIL"
    extra = ""
    if r["success"]:
        extra = f"  ({r['elapsed']:.1f}s)"
        any_success = True
    else:
        extra = f"  — {r.get('error','')}"
    print(f"  {status}  {r['project']}{extra}")

print(f"\n{'='*60}")
if any_success:
    print("AT LEAST ONE PROJECT CONFIRMED SUCCESSFUL CALL — safe to proceed to full run.")
else:
    print("ALL PROJECTS FAILED — do NOT proceed to full run.")
print(f"{'='*60}\n")
