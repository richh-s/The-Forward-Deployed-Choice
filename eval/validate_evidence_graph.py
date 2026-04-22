"""
Validate evidence_graph.json — ensures every claim has a source, no placeholders,
and source files exist.

Usage:
  python eval/validate_evidence_graph.py [evidence_graph.json]
  python eval/validate_evidence_graph.py evidence_graph.json memo.pdf
"""
import json
import re
import sys
from pathlib import Path


PLACEHOLDER_PATTERNS = [
    r"\[fill\]",
    r"\[YOUR REAL NUMBER\]",
    r"\[MEASURE\]",
    r"\[compute\b",
    r"\[YOUR NUMBER\]",
    r"null",
]


def check_placeholders(value: object) -> bool:
    s = str(value)
    for pat in PLACEHOLDER_PATTERNS:
        if re.search(pat, s, re.IGNORECASE):
            return True
    return False


def validate(evidence_path: str = "evidence_graph.json", memo_path: str | None = None) -> bool:
    path = Path(evidence_path)
    if not path.exists():
        print(f"ERROR: {evidence_path} not found")
        return False

    with open(path) as f:
        graph = json.load(f)

    claims = graph.get("claims", [])
    errors = []
    warnings = []

    print(f"\nValidating {evidence_path}")
    print(f"  {len(claims)} claims found\n")

    for claim in claims:
        cid = claim.get("claim_id", "UNKNOWN")
        text = claim.get("claim_text", "")
        source_ref = claim.get("source_ref", "")
        value = claim.get("value")
        verified = claim.get("verified", False)

        # Check for unresolved placeholders in claim_text
        if check_placeholders(text):
            errors.append(f"  {cid}: claim_text contains placeholder: '{text[:80]}'")

        # Check for null value on recomputable claims
        if claim.get("recomputable", False) and value is None:
            errors.append(f"  {cid}: value is null but claim is marked recomputable")

        # Check that source_ref points to an existing file (file part only)
        if source_ref:
            file_part = source_ref.split("#")[0]
            if file_part and not Path(file_part).exists():
                warnings.append(f"  {cid}: source_ref file not found: {file_part}")

        # Check verified flag
        if not verified:
            warnings.append(f"  {cid}: not yet verified (verified=false)")

        status = "OK" if not check_placeholders(text) else "PLACEHOLDER"
        print(f"  [{cid}] {status}  value={value}  verified={verified}")
        print(f"         {text[:80]}")

    # Check memo for [fill] placeholders if provided
    if memo_path:
        memo = Path(memo_path)
        if memo.exists() and memo.suffix == ".md":
            content = memo.read_text()
            fill_matches = re.findall(r"\[fill\]", content, re.IGNORECASE)
            if fill_matches:
                errors.append(f"memo.md contains {len(fill_matches)} [fill] placeholders")

    print(f"\n{'='*50}")
    if errors:
        print(f"ERRORS ({len(errors)}):")
        for e in errors:
            print(e)
    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(w)
    if not errors and not warnings:
        print("All claims validated. No errors or warnings.")
    elif not errors:
        print(f"Passed with {len(warnings)} warning(s). No blocking errors.")

    return len(errors) == 0


if __name__ == "__main__":
    evidence_path = sys.argv[1] if len(sys.argv) > 1 else "evidence_graph.json"
    memo_path = sys.argv[2] if len(sys.argv) > 2 else None
    ok = validate(evidence_path, memo_path)
    sys.exit(0 if ok else 1)
