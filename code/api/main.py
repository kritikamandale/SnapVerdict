"""
FastAPI backend for single-claim processing.

Wraps process_claim() behind a simple HTTP API.  Designed for
portfolio/academic demo — no queue, no database, no auth.

Run locally (from repo root):
    uvicorn --app-dir code api.main:app --reload --port 8000

Render start command:
    uvicorn code.api.main:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path

# Resolve repo root (two levels up from code/api/main.py) and add code/ to path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "code"))

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from pipeline.process_claim import process_claim

app = FastAPI(
    title="SnapVerdict API",
    description="Multi-modal damage claim verification",
    version="0.1.0",
)

# CORS: read allowed origins from ALLOWED_ORIGIN env var.
# Use * for local dev or to allow all origins during demo.
_allowed = os.environ.get("ALLOWED_ORIGIN", "*")
_allow_origins = [o.strip() for o in _allowed.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_ROOT = _REPO_ROOT / "dataset" / "images" / "uploads"


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/claims")
async def create_claim(
    images: list[UploadFile] = File(...),
    user_claim: str = Form(...),
    claim_object: str = Form(...),
) -> dict:
    claim_id = uuid.uuid4().hex[:12]
    claim_dir = UPLOAD_ROOT / claim_id
    claim_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[str] = []
    try:
        for idx, upload in enumerate(images, start=1):
            ext = Path(upload.filename or "img.jpg").suffix or ".jpg"
            fname = f"img_{idx}{ext}"
            dest = claim_dir / fname
            content = await upload.read()
            dest.write_bytes(content)
            # Relative path from repo root, as process_claim expects
            saved_paths.append(f"images/uploads/{claim_id}/{fname}")

        claim = {
            "user_id": f"api_{claim_id}",
            "claim_object": claim_object.strip().lower(),
            "user_claim": user_claim.strip(),
            "image_paths": saved_paths,
        }

        result = process_claim(claim)
        return result

    except EnvironmentError as exc:
        msg = str(exc)
        if "exhausted" in msg.lower():
            return {
                "error": True,
                "error_type": "quota_exhausted",
                "error_message": (
                    "Demo is at daily API capacity — please try again later."
                ),
            }
        return {
            "error": True,
            "error_type": "pipeline_error",
            "error_message": msg,
        }

    except Exception as exc:
        return {
            "error": True,
            "error_type": "internal_error",
            "error_message": str(exc),
        }

    finally:
        if claim_dir.exists():
            shutil.rmtree(claim_dir, ignore_errors=True)
