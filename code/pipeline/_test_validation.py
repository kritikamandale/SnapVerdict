"""
Quick validation tests for process_claim().

Verifies that invalid inputs return clean error dicts instead of crashing.
No Gemini API calls — all 4 test cases fail validation before reaching vision.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.process_claim import process_claim

_PASS = 0
_FAIL = 0


def _label(test_name: str) -> str:
    return f"[TEST] {test_name}"


def run_test(name: str, claim: dict, expect_error_substring: str) -> None:
    global _PASS, _FAIL
    print(_label(name), end=" ... ")
    try:
        result = process_claim(claim)
    except Exception as exc:
        print(f"FAIL — crashed with {type(exc).__name__}: {exc}")
        _FAIL += 1
        return

    if not result.get("error"):
        print(f"FAIL — expected error=True, got: {result}")
        _FAIL += 1
        return

    msg = result.get("error_message", "")
    if expect_error_substring.lower() in msg.lower():
        print(f"PASS — error_message: {msg}")
        _PASS += 1
    else:
        print(f"FAIL — expected substring '{expect_error_substring}' "
              f"in error_message, got: {msg}")
        _FAIL += 1


def main() -> None:
    global _PASS, _FAIL

    # --- Test 1: missing file ---
    run_test(
        "Missing image file",
        {
            "claim_object": "car",
            "user_claim": "Scratch on the front bumper",
            "image_paths": ["images/sample/nonexistent_file.jpg"],
        },
        "not found",
    )

    # --- Test 2: non-image file (.txt renamed to .jpg) ---
    tmp = tempfile.NamedTemporaryFile(
        dir=str(Path("dataset") / "images" / "sample"),
        prefix="fake_", suffix=".jpg", delete=False,
    )
    tmp.write(b"this is not an image, just plain text")
    tmp.close()
    fake_name = Path(tmp.name).name
    try:
        run_test(
            "Non-image file (txt disguised as jpg)",
            {
                "claim_object": "car",
                "user_claim": "Cracked windshield from road debris",
                "image_paths": [f"images/sample/{fake_name}"],
            },
            "not a valid image",
        )
    finally:
        os.unlink(tmp.name)

    # --- Test 3: empty claim_object ---
    run_test(
        "Empty claim_object",
        {
            "claim_object": "",
            "user_claim": "My laptop screen is cracked",
            "image_paths": ["images/sample/img_1.jpg"],
        },
        "claim_object is required",
    )

    # --- Test 4: empty user_claim ---
    run_test(
        "Empty user_claim text",
        {
            "claim_object": "package",
            "user_claim": "",
            "image_paths": ["images/sample/img_1.jpg"],
        },
        "user_claim is required",
    )

    # --- Summary ---
    total = _PASS + _FAIL
    print(f"\n{'='*48}")
    print(f"RESULTS: {_PASS}/{total} passed, {_FAIL}/{total} failed")
    print(f"{'='*48}")
    if _FAIL:
        sys.exit(1)


if __name__ == "__main__":
    main()
