#!/usr/bin/env python3
"""Ingest the NDIS Provider Register CSV into the ndis-provider.schema.json shape.

Source: https://www.ndiscommission.gov.au/provider-registration/find-registered-provider/download-csv
Licence: CC BY 4.0 Australia (attribution carried through in each record's 'source' block).

See ../schema/ndis-provider-schema-notes.md for the field mapping and the reasoning
behind the entity_type / legal_name privacy handling below.
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

REGISTER_NAME = "NDIS Provider Register"
LICENCE = "CC BY 4.0 AU"

# ABR sole-trader convention: "SURNAME, Given Name(s)". Word-boundary exclusion
# stops names like "Sinclair" or "Vincent" false-positiving on the substring "inc".
INDIVIDUAL_NAME_RE = re.compile(r"^[A-Za-z'\-]+(\s[A-Za-z'\-]+)?,\s+[A-Za-z'\-]+(\s[A-Za-z'\-]+){0,3}$")
ORG_WORD_RE = re.compile(
    r"\b(pty|ltd|inc|incorporated|association|assoc|trust|corporation|corp|limited|llc|"
    r"foundation|council|group|centre|center|services|industries|enterprises|company|"
    r"co-operative|cooperative)\b",
    re.IGNORECASE,
)

ADDRESS_RE = re.compile(r"^(?P<suburb>.+), (?P<state>[A-Z]{2,3}), (?P<postcode>\d{4}), (?P<country>[A-Z]{2})$")

MONTHS = {
    "January": "01", "February": "02", "March": "03", "April": "04",
    "May": "05", "June": "06", "July": "07", "August": "08",
    "September": "09", "October": "10", "November": "11", "December": "12",
}
EXPIRY_RE = re.compile(r"^(\d{1,2}) (\w+) (\d{4})$")


def classify_entity(legal_name: str) -> str:
    name = legal_name.strip()
    if INDIVIDUAL_NAME_RE.match(name) and not ORG_WORD_RE.search(name):
        return "individual"
    return "organisation"


def parse_expiry(value: str):
    value = value.strip()
    if not value:
        return None
    m = EXPIRY_RE.match(value)
    if not m:
        return None
    day, month_name, year = m.groups()
    month = MONTHS.get(month_name)
    if not month:
        return None
    return f"{year}-{month}-{int(day):02d}"


def parse_head_office(address: str):
    m = ADDRESS_RE.match(address.strip())
    if not m:
        return {"suburb": None, "state": None, "postcode": None, "country": "AU"}
    d = m.groupdict()
    return {"suburb": d["suburb"], "state": d["state"], "postcode": d["postcode"], "country": d["country"]}


def build_outlet(row: dict):
    name = row["Outlet name"].strip() or None
    address = row["Outlet address"].strip() or None
    # The source fills a missing outlet address with just the country code
    # (~13% of outlets) — treat that as no address, not a real one.
    if address == "AU":
        address = None
    phone = row["Outlet phone"].strip() or None
    if name is None and address is None and phone is None:
        return None
    return {"name": name, "address": address, "phone": phone}


def build_provider(abn: str, rows: list, retrieved_at: str):
    first = rows[0]

    # Data quality quirk, not expected to be meaningful: ~6/29,441 providers have a
    # different status on different outlet rows. Take the first and flag it rather
    # than guess which row is authoritative.
    statuses = {r["Registration status"].strip() for r in rows if r["Registration status"].strip()}
    if len(statuses) > 1:
        print(
            f"WARNING: ABN {abn} has inconsistent Registration status across rows: "
            f"{statuses} - using first row's value ({first['Registration status'].strip()})",
            file=sys.stderr,
        )
    status = first["Registration status"].strip()

    # Union across a provider's outlet rows: if different outlets are approved for
    # different service categories, the provider overall offers the superset.
    categories = set()
    for r in rows:
        for c in r["Approved registration groups"].split(";"):
            c = c.strip()
            if c:
                categories.add(c)

    legal_name = first["Legal name"].strip()
    entity_type = classify_entity(legal_name)

    outlets = []
    for r in rows:
        outlet = build_outlet(r)
        if outlet:
            outlets.append(outlet)

    return {
        "provider_id": abn,
        "business_name": first["Provider business name"].strip(),
        # Deliberate minimisation, not a licence requirement: sole traders' personal
        # legal names aren't republished even though the source licence permits it.
        "legal_name": None if entity_type == "individual" else legal_name,
        "entity_type": entity_type,
        "registration_status": status,
        "registration_expiry": parse_expiry(first["Period of registration in force until"]),
        "service_categories": sorted(categories),
        "has_registration_conditions": any(r["Conditions of registration"].strip() for r in rows),
        "website": first["Website"].strip() or None,
        "head_office": parse_head_office(first["Head office address"]),
        "outlets": outlets,
        "last_verified": retrieved_at,
        "source": {
            "register": REGISTER_NAME,
            "licence": LICENCE,
            "retrieved_at": retrieved_at,
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Ingest NDIS Provider Register CSV into the agent-readable provider schema."
    )
    parser.add_argument("input_csv", help="Path to the downloaded NDIS Provider Register CSV")
    parser.add_argument("output_jsonl", help="Path to write the output JSON Lines file")
    parser.add_argument(
        "--limit", type=int, default=None, help="Only process the first N providers (for quick testing)"
    )
    args = parser.parse_args()

    retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(args.input_csv, encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    groups = defaultdict(list)
    for r in rows:
        groups[r["ABN"].strip()].append(r)

    abns = list(groups.keys())
    if args.limit:
        abns = abns[: args.limit]

    individual_count = 0
    revoked_count = 0
    blank_address_count = 0

    with open(args.output_jsonl, "w", encoding="utf-8") as out:
        for abn in abns:
            provider = build_provider(abn, groups[abn], retrieved_at)
            if provider["entity_type"] == "individual":
                individual_count += 1
            if provider["registration_status"] == "Revoked":
                revoked_count += 1
            if provider["head_office"]["suburb"] is None:
                blank_address_count += 1
            out.write(json.dumps(provider, ensure_ascii=False) + "\n")

    print(f"Wrote {len(abns)} providers to {args.output_jsonl}", file=sys.stderr)
    print(f"  individual (sole trader) entities: {individual_count}", file=sys.stderr)
    print(f"  revoked registrations: {revoked_count}", file=sys.stderr)
    print(f"  unparseable head office address: {blank_address_count}", file=sys.stderr)


if __name__ == "__main__":
    main()
