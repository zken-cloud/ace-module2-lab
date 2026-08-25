#!/usr/bin/env python3
"""Select finding IDs from a `cm report -f json` by status (Module 2 lab).

Used by the "Verify Findings" step. `cm find verify` marks a finding VERIFIED
(real) or DISMISSED (false positive); when it can't build/run the app to confirm
(this pipeline scans code only) it may leave the status unchanged (OPEN). So the
fix step should remediate every candidate EXCEPT the ones verify actively
DISMISSED — expressed here as `not:DISMISSED`.

Usage:
  cm_select.py <report.json> <STATUS>      [candidate_id ...]   # keep status == STATUS
  cm_select.py <report.json> not:<STATUS>  [candidate_id ...]   # keep status != STATUS

Prints a space-separated list of matching FindingIDs (case-insensitive status),
restricted to <candidate_id ...> when given. Never exits non-zero; tolerates a
banner before the JSON by reusing cm_triage's parser.
"""
from __future__ import annotations

import os
import sys

# Reuse the robust, banner-tolerant parsing from the triage script next door.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cm_triage import extract_findings, _get  # noqa: E402


def main() -> int:
    report_path = sys.argv[1] if len(sys.argv) > 1 else ""
    spec = (sys.argv[2] if len(sys.argv) > 2 else "VERIFIED")
    negate = spec.lower().startswith("not:")
    want_status = (spec.split(":", 1)[1] if negate else spec).upper()
    candidates = set(sys.argv[3:])  # empty => no restriction

    raw = ""
    if report_path and os.path.exists(report_path):
        with open(report_path, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()

    ids = []
    for f in extract_findings(raw):
        fid = str(_get(f, "FindingID", "finding_id", "id", default=""))
        status = str(_get(f, "Status", "status", "State", default="")).upper()
        if not fid:
            continue
        matches = (status != want_status) if negate else (status == want_status)
        if not matches:
            continue
        if candidates and fid not in candidates:
            continue
        ids.append(fid)

    print(" ".join(ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())
