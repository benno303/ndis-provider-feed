# NDIS provider schema — source mapping and decisions

Verified against a live pull of the NDIS Provider Register CSV on 2026-09-17
(ndiscommission.gov.au/provider-registration/find-registered-provider/download-csv,
63,573 rows / 29,441 unique ABNs). Re-verify these stats against a fresh pull before
building the ingestion script — the register updates regularly.

## Source shape

The CSV is **one row per outlet**, not one row per provider — a provider with 3
outlets appears as 3 rows sharing the same ABN. The schema (`ndis-provider.schema.json`)
reflects this: one JSON object per provider (keyed on ABN), with outlets nested as an array.
Don't flatten this back to one-row-per-outlet in the API — that would duplicate
identity/compliance fields across records for no reason and make "how many outlets
does this provider have" unanswerable.

## Field-by-field

| Source column | Schema field | Notes |
|---|---|---|
| `Provider business name` | `business_name` | Always safe to display, always present. |
| `Legal name` | `legal_name` | **Withheld when `entity_type` is `individual`** — see Privacy decision below. |
| `ABN` | `provider_id` | Used as the stable key. Already public via ABN Lookup, so no incremental privacy exposure. |
| `Head office address` | `head_office.{suburb,state,postcode,country}` | 100% consistent `SUBURB, STATE, POSTCODE, COUNTRY` format in 63,569/63,573 rows; the remaining 4 are blank (`AU` only) — handle as a null/unknown case, don't crash the parser on it. |
| `Website` | `website` | Blank in ~24% of rows — nullable. |
| `Registration status` | `registration_status` | Only `Approved` and `Revoked` observed in this pull. Kept as an open string, not a hardcoded 2-value enum, in case `Suspended` or others appear in a future extract (the NDIS Commission's own site references suspension as a possible state elsewhere). |
| `Period of registration in force until` | `registration_expiry` | Source format `DD Month YYYY` (e.g. `22 September 2026`) — parse to ISO 8601 date. |
| `Approved registration groups` | `service_categories` | Semicolon-separated in source. Verified exactly 38 distinct values across the full file — see the enum in the schema file. **Regenerate this enum from a fresh pull at build time**; don't treat the hardcoded list as permanent, the Commission can add categories. |
| `Conditions of registration` | `has_registration_conditions` (boolean only) | Non-empty in 54.3% of rows. The raw text is long, free-form, and had visible encoding artifacts in the pulled file (e.g. a mis-encoded apostrophe rendering as `?`) — not worth exposing raw in a v1 public schema. Revisit as a Phase 2 "verified/detail tier" field once there's a reason to clean and expose it (e.g. an agent developer specifically asks for it). |
| `Outlet name` / `Outlet address` / `Outlet phone` | `outlets[]` | Present at very different rates: name 88.6%, phone 79.3%, address only 53.8%. Expect a lot of outlets with a name and phone but no address — don't assume address is always populated. |
| — (not in source) | `entity_type` | Derived field, not from source data. See Privacy decision below. |
| — (not in source) | `last_verified` | Set by the ingestion pipeline, not the source. It's the basis of the feed's trust story — populate it honestly (actual pull time), never backfill a fake earlier date. |
| — (not in source) | `source.*` | Attribution block. The NDIS Commission's site content is CC BY 4.0 AU, which requires attribution — this satisfies that for anything built from the register. |

## Privacy decision: `entity_type` and withholding `legal_name`

The register contains real individuals trading as sole traders under their own name —
legal names in the ABR sole-trader form `SURNAME, Given Names` (illustrative, not real:
`CITIZEN, JANE MARY` trading as "Jane's Physio", or `CITIZEN, JOHN` trading as "John
Citizen", where the trading name *is* the personal name). A rough heuristic (legal name containing
no company-type suffix such as Pty/Ltd/Inc/Association) flags ~21% of rows, though that
heuristic also over-catches other entity types (councils, foundations, associations) —
it's a starting point for a manual/rules-based classifier, not a finished one.

**Decision:** classify each row into `entity_type: organisation | individual` at ingestion
time, and only populate `legal_name` for organisations. For individuals, `legal_name` is
`null` and `business_name` (the trading name) is used instead.

This is a minimisation choice, not a legal requirement — the register's CC BY 4.0 licence
permits reusing the legal name field as published. But the product's actual purpose
(helping someone find and compare a provider) doesn't need a sole trader's personal legal
name, so there's no reason to republish it. It's also part of handling the data with care,
ahead of it actually mattering commercially.

Building the classifier properly (rather than the rough suffix heuristic above) is a Phase 0
build task, not a schema task — flagging it here so it isn't lost.

**Update:** the suffix heuristic above was superseded during ingestion script development.
The working classifier instead matches the ABR sole-trader naming convention directly —
`SURNAME, Given Name(s)` — then excludes anything containing a company-type word
(Pty/Ltd/Inc/Association/etc., matched on word boundaries so "Sinclair" or "Vincent" don't
false-positive on the substring "inc"). Verified against the full pulled file: 4,457/63,573
rows (7.0%) classified as individual, zero false positives found on manual review (a first
pass without word-boundary matching caught 3 real false positives — org names like "We Care,
You Heal Pty Ltd" — before the fix). See `ingest/ingest_ndis.py::classify_entity`.

## Grouping edge cases found while building the ingestion script

- **6 of 29,441 providers** have a different `Registration status` on different outlet rows
  for the same ABN (data quality quirk in the source, not expected to be meaningful). The
  ingestion script takes the first row's value and logs a warning rather than guessing which
  is authoritative — worth a manual look if these matter later, not worth engineering around now.
- **9 of 29,441 providers** have different `Approved registration groups` strings across their
  outlet rows. Handled by taking the **union** of categories across all of a provider's rows —
  this is a real design decision, not just an edge-case shrug: if different outlets are
  approved for different services, the provider overall offers the superset.
- **4 rows** have an unparseable `Head office address` (source value was literally just `AU`).
  `head_office.suburb/state/postcode` are `null` for these rather than a fabricated value —
  schema updated to allow this (see `ndis-provider.schema.json`).
