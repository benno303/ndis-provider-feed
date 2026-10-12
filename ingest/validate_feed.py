#!/usr/bin/env python3
"""Sanity-check a freshly ingested feed before it's deployed.

Run by the weekly refresh workflow between ingestion and deploy. Exits non-zero
(and so blocks the deploy, leaving the last good data live) if the new file looks
wrong — e.g. the Commission changed their CSV format, the download was truncated,
or a new service category appeared that the schema doesn't know about yet.

The bounds are deliberately loose: they catch a broken pipeline, not normal
week-to-week churn (~233 providers added and ~100 removed over four weeks in
Sep-Oct 2026).

Usage: python ingest/validate_feed.py <ingested.jsonl>
"""

import json
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "ndis-provider.schema.json"

MIN_PROVIDERS = 25_000  # 29,574 on 2026-10-13
MAX_PROVIDERS = 40_000
MIN_APPROVED_SHARE = 0.80  # 92.5% on 2026-10-13
MIN_HEAD_OFFICE_STATE_SHARE = 0.99  # all but 4 records on 2026-10-13


def main(path: Path) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    known_categories = set(schema["properties"]["service_categories"]["items"]["enum"])
    required = schema["required"]

    records = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
    problems = []

    n = len(records)
    if not MIN_PROVIDERS <= n <= MAX_PROVIDERS:
        problems.append(f"provider count {n} outside expected range {MIN_PROVIDERS}-{MAX_PROVIDERS}")
    if n == 0:
        return problems

    missing = [r.get("provider_id", "?") for r in records if any(f not in r for f in required)]
    if missing:
        problems.append(f"{len(missing)} records missing required fields, e.g. {missing[:3]}")

    approved = sum(1 for r in records if r.get("registration_status") == "Approved")
    if approved / n < MIN_APPROVED_SHARE:
        problems.append(f"only {approved / n:.1%} of providers Approved (expected >= {MIN_APPROVED_SHARE:.0%})")

    with_state = sum(1 for r in records if (r.get("head_office") or {}).get("state"))
    if with_state / n < MIN_HEAD_OFFICE_STATE_SHARE:
        problems.append(f"only {with_state / n:.1%} have a head office state - address format may have changed")

    unknown = {c for r in records for c in r.get("service_categories", [])} - known_categories
    if unknown:
        problems.append(
            f"new service categories not in schema enum: {sorted(unknown)} - "
            "add them to schema/ndis-provider.schema.json so list_service_categories() includes them"
        )

    print(f"{n} providers, {approved} approved, {len(known_categories)} known categories")
    return problems


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    problems = main(Path(sys.argv[1]))
    if problems:
        print("VALIDATION FAILED - not deploying:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)
    print("Validation passed.")
