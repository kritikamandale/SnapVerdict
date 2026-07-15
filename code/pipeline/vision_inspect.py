"""
Vision inspection stage — powered by Google Gemini API.

Gemini is used here specifically because it offers a free tier with no
expiring trial credit and no credit card required, making it suitable for
prototyping this pipeline without incurring API costs. Claude Code remains
the build tool; only these inference calls go through Gemini.

Project-aware key management: keys are grouped by GCP project. Each
project has its own 20 req/day free-tier quota. Round-robin rotates
across PROJECTS first, then across keys within a project. A 429 on any
key immediately marks the entire project as exhausted and moves to the
next project's keys — no wasted retries on sibling keys in the same
dead project.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv
import google.genai as genai
from google.genai import errors as genai_errors
from google.genai import types

from config.prompts import SYSTEM_PROMPT, build_user_prompt, OBJECT_PART_LISTS

# ---------------------------------------------------------------------------
# Project-aware key management
# ---------------------------------------------------------------------------
# Keys are grouped by GCP project.  Each project shares a single
# 20 req/day free-tier quota for gemini-2.5-flash.  Keys within the same
# project do NOT have independent quotas.
#
# Round-robin rotates across projects, then across keys within a project.
# On a 429, the entire project is marked exhausted — no further keys in
# that project are attempted for the rest of the run.
# ---------------------------------------------------------------------------

load_dotenv()

# Static config: project name → {keys, model}
_PROJECT_CONFIG: dict[str, dict] = {
    "gen-lang-client-0765394622": {
        "keys": [
            "GEMINI_API_KEY_1", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3",
            "GEMINI_API_KEY_4", "GEMINI_API_KEY_5", "GEMINI_API_KEY_6",
        ],
        "model": "gemini-2.5-flash",
    },
    "rankproject-502415": {
        "keys": ["GEMINI_API_KEY_7", "GEMINI_API_KEY_10"],
        "model": "gemini-2.0-flash",
    },
    "ambient-sphere-502415-a7": {
        "keys": ["GEMINI_API_KEY_8", "GEMINI_API_KEY_9"],
        "model": "gemini-2.0-flash",
    },
}


def _load_projects() -> tuple[list[str], dict[str, list[tuple[int, str]]], dict[str, str]]:
    """Load API keys from env, grouped by GCP project.

    Returns (project_names, project_keys, project_models) where:
      - project_keys maps project name to [(key_number, key_value), ...]
      - project_models maps project name to its model string
    Projects with no loadable keys are excluded.
    """
    projects: list[str] = []
    project_keys: dict[str, list[tuple[int, str]]] = {}
    project_models: dict[str, str] = {}
    for proj, cfg in _PROJECT_CONFIG.items():
        keys: list[tuple[int, str]] = []
        for var in cfg["keys"]:
            k = os.environ.get(var, "").strip()
            if k:
                num = int(var.rsplit("_", 1)[-1])
                keys.append((num, k))
        if keys:
            projects.append(proj)
            project_keys[proj] = keys
            project_models[proj] = cfg["model"]
    return projects, project_keys, project_models


_projects: list[str]
_project_keys: dict[str, list[tuple[int, str]]]
_project_models: dict[str, str]
_projects, _project_keys, _project_models = _load_projects()

_current_project_idx: int = 0
_current_key_in_project: dict[str, int] = {}   # project → next key index within project
_exhausted_projects: set[str] = set()


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

class VisionResult(TypedDict):
    # evidence gate (see decide.py for how this overrides evidence_check output)
    evidence_standard_met_override: bool   # False → vision downgrades count-based True
    evidence_standard_met_reason: str
    # claim assessment
    issue_type: str
    object_part: str
    claim_status: str
    claim_status_justification: str
    supporting_image_ids: list[str]
    valid_image: bool
    severity: str
    risk_flags: list[str]
    # provenance
    model: str  # which Gemini model processed this claim


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MEDIA_TYPES: dict[str, str] = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".gif":  "image/gif",
    ".webp": "image/webp",
}


def _load_image(path: str) -> tuple[bytes, str]:
    """Return (raw_bytes, media_type) for an image file."""
    ext = Path(path).suffix.lower()
    media_type = _MEDIA_TYPES.get(ext, "image/jpeg")
    with open(path, "rb") as fh:
        return fh.read(), media_type


def _parse_json(raw: str) -> dict:
    """Extract a JSON object from the model response."""
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if text.startswith("```"):
        lines = text.split("\n")
        body = lines[1:]
        if body and body[-1].strip() == "```":
            body = body[:-1]
        text = "\n".join(body).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError(f"Could not extract JSON from model response: {raw[:300]!r}")


def _sanitize_object_part(raw_value: str, claim_object: str) -> str:
    """Map model output to an exact allowed object_part value."""
    allowed = OBJECT_PART_LISTS.get(claim_object, ["unknown"])
    lower = raw_value.strip().lower()

    if lower in allowed:
        return lower

    underscored = lower.replace(" ", "_")
    if underscored in allowed:
        print(f"[vision] object_part '{raw_value}' mapped to '{underscored}'")
        return underscored

    stripped_the = lower
    if stripped_the.startswith("the "):
        stripped_the = stripped_the[4:]
    underscored_the = stripped_the.replace(" ", "_")
    if underscored_the in allowed:
        print(f"[vision] object_part '{raw_value}' mapped to '{underscored_the}'")
        return underscored_the

    stripped = stripped_the
    for prefix in ("car ", "laptop ", "package "):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
            break
    underscored_stripped = stripped.replace(" ", "_")
    if underscored_stripped in allowed:
        print(f"[vision] object_part '{raw_value}' mapped to '{underscored_stripped}'")
        return underscored_stripped

    for part in allowed:
        if part.lower() == lower:
            print(f"[vision] object_part '{raw_value}' mapped to '{part}' (case-insensitive)")
            return part

    print(f"[vision] WARNING: object_part '{raw_value}' not in allowed list for {claim_object}, falling back to 'unknown'")
    return "unknown"


def _is_retryable(exc: Exception) -> bool:
    """True if exc is a transient error worth retrying (429 or 503)."""
    code = getattr(exc, "code", None)
    if code in (429, 503):
        return True
    s = str(exc).upper()
    return "429" in s or "RESOURCE_EXHAUSTED" in s or "503" in s or "UNAVAILABLE" in s


def _is_429(exc: Exception) -> bool:
    """True specifically for RESOURCE_EXHAUSTED / quota errors."""
    code = getattr(exc, "code", None)
    if code == 429:
        return True
    s = str(exc).upper()
    return "429" in s or "RESOURCE_EXHAUSTED" in s


# ---------------------------------------------------------------------------
# Project-aware round-robin helpers
# ---------------------------------------------------------------------------

def _pick_next_target(from_project_idx: int) -> tuple[str, int, str, str] | None:
    """Pick the next (project_name, key_number, key_value, model) to call.

    Rotates across non-exhausted projects, then across keys within the
    chosen project.  Returns None if all projects are exhausted.
    """
    n = len(_projects)
    for _ in range(n):
        idx = from_project_idx % n
        proj = _projects[idx]
        if proj not in _exhausted_projects:
            keys = _project_keys[proj]
            key_idx = _current_key_in_project.get(proj, 0) % len(keys)
            key_num, key_val = keys[key_idx]
            model = _project_models[proj]
            return proj, key_num, key_val, model
        from_project_idx += 1
    return None


def _advance_cursor() -> None:
    """Advance the round-robin cursor after a successful call.

    Advances the key index within the current project.  If the key pool
    is exhausted (or the project itself is exhausted), moves to the next
    non-exhausted project and resets its key index to 0.
    """
    global _current_project_idx
    n = len(_projects)
    for _ in range(n):
        proj = _projects[_current_project_idx % n]
        if proj in _exhausted_projects:
            _current_project_idx = (_current_project_idx + 1) % n
            continue
        keys = _project_keys[proj]
        ki = _current_key_in_project.get(proj, 0) + 1
        if ki >= len(keys):
            # All keys in this project used — move to next project
            _current_project_idx = (_current_project_idx + 1) % n
            _current_key_in_project[proj] = 0
        else:
            _current_key_in_project[proj] = ki
        return


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def inspect_claim_images(
    claim_object: str,
    user_claim_text: str,
    image_paths: list[str],
) -> VisionResult:
    """Single Gemini vision call for all images belonging to one claim.

    image_paths must be openable from the current working directory.
    Path resolution is the caller's responsibility.

    Uses project-aware round-robin: rotates across GCP projects, then
    across keys within a project.  On a 429 the entire project is marked
    exhausted and the next project's keys are tried immediately.
    """
    global _current_project_idx

    if not _projects:
        raise EnvironmentError(
            "No Gemini API keys found. "
            "Set GEMINI_API_KEY_1, GEMINI_API_KEY_2, ... in .env "
            "or your shell."
        )

    image_ids = [Path(p).stem for p in image_paths]

    # Content layout: [user prompt text] [img_label] [img_bytes] ... [final instruction]
    parts: list[types.Part] = [
        types.Part.from_text(text=build_user_prompt(claim_object, user_claim_text, image_ids))
    ]
    for path, img_id in zip(image_paths, image_ids):
        raw_bytes, media_type = _load_image(path)
        parts.append(types.Part.from_text(text=f"[{img_id}]"))
        parts.append(types.Part.from_bytes(data=raw_bytes, mime_type=media_type))
    parts.append(types.Part.from_text(text="Return only the JSON object:"))

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
    )

    def _call(key_val: str, model: str) -> types.GenerateContentResponse:
        client = genai.Client(api_key=key_val)
        return client.models.generate_content(
            model=model,
            contents=parts,
            config=config,
        )

    # ------------------------------------------------------------------
    # Phase 1: try the round-robin target (project + key).
    # ------------------------------------------------------------------
    response: types.GenerateContentResponse | None = None
    first_exc: genai_errors.APIError | None = None
    start_proj_idx = _current_project_idx
    start_proj_name: str | None = None
    start_key_val: str | None = None
    start_model: str | None = None

    target = _pick_next_target(start_proj_idx)
    if target is None:
        # All projects exhausted — Phase 3 will handle backoff
        pass
    else:
        proj_name, key_num, key_val, model = target
        start_proj_name = proj_name
        start_key_val = key_val
        start_model = model
        print(f"[vision] project={proj_name} key={key_num} model={model}")
        try:
            response = _call(key_val, model)
            _advance_cursor()
        except genai_errors.APIError as exc:
            if not _is_retryable(exc):
                raise
            first_exc = exc

    # ------------------------------------------------------------------
    # Phase 2: primary returned 429 — mark entire project exhausted,
    # try the next project immediately.  Repeat until we find a
    # working project or all projects are exhausted.
    # ------------------------------------------------------------------
    if response is None and first_exc is not None and _is_429(first_exc):
        if start_proj_name:
            _exhausted_projects.add(start_proj_name)
            print(f"[vision] project {start_proj_name} exhausted (429 on key {start_proj_name})")

        remaining = len(_projects) - len(_exhausted_projects)
        current_proj_idx = (_current_project_idx + 1) % len(_projects) if _projects else 0

        while remaining > 0:
            target = _pick_next_target(current_proj_idx)
            if target is None:
                break
            proj_name, key_num, key_val, model = target
            print(f"[vision] project={proj_name} key={key_num} model={model}")
            try:
                response = _call(key_val, model)
                start_model = model  # update for Phase 3 fallback
                _advance_cursor()
                break
            except genai_errors.APIError as exc2:
                if not _is_retryable(exc2):
                    raise
                if _is_429(exc2):
                    _exhausted_projects.add(proj_name)
                    print(f"[vision] project {proj_name} exhausted (429 on key {key_num})")
                    current_proj_idx = (current_proj_idx + 1) % len(_projects)
                    remaining -= 1
                else:
                    break

        if response is None and len(_exhausted_projects) >= len(_projects):
            print(
                f"[vision] all {len(_projects)} projects exhausted; "
                "falling back to wait-and-retry "
                "(may be a per-minute limit rather than daily cap)"
            )

    # ------------------------------------------------------------------
    # Phase 3: all projects exhausted — exponential backoff on the
    # starting project's key (per-minute limit may recover).
    # ------------------------------------------------------------------
    if response is None and start_proj_name and start_key_val and start_model:
        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                print(f"[vision] project={start_proj_name} key=retry attempt {attempt + 1}/{max_retries}")
                response = _call(start_key_val, start_model)
                _advance_cursor()
                break
            except genai_errors.APIError as exc:
                if not _is_retryable(exc) or attempt == max_retries:
                    raise
                wait = 65 if _is_429(exc) else 2 ** attempt
                print(f"[vision] retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)

    if response is None:
        exhausted = ", ".join(sorted(_exhausted_projects)) if _exhausted_projects else "none"
        raise EnvironmentError(
            f"All Gemini projects exhausted — no working API key available. "
            f"Exhausted projects: [{exhausted}]. "
            f"Retry tomorrow when free-tier daily quota resets."
        )

    raw = response.text
    result: VisionResult = _parse_json(raw)  # type: ignore[assignment]
    result["object_part"] = _sanitize_object_part(result.get("object_part", ""), claim_object)
    result["model"] = start_model or "unknown"
    return result
