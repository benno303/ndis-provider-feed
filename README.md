# NDIS Provider Feed

An [MCP](https://modelcontextprotocol.io) server that makes Australia's **NDIS Provider Register**, the official register of disability support providers, available as clean, structured data that AI assistants and agents can query directly.

The register is public, but the only official way to search it is a web form and a bulk CSV with one row per outlet. This feed turns it into one record per provider, keyed by ABN, with search by location and service category.

- **Free, no sign-up.** The register feed is free and will stay free.
- **Refreshed weekly** from the official register by an [automated job](.github/workflows/refresh.yml), with checks that block a bad refresh from going live.
- **Hosted in Sydney** on Google Cloud Run.
- Listed on the [official MCP Registry](https://registry.modelcontextprotocol.io/v0.1/servers?search=ndis-provider-feed) as `io.github.benno303/ndis-provider-feed`.

> **Not an official source.** This project isn't affiliated with or endorsed by the NDIS Quality and Safeguards Commission or the NDIA. It mirrors their public register and can lag it by up to a week. Check the [official register](https://www.ndiscommission.gov.au/provider-registration/find-registered-provider) before relying on a provider's registration status for any decision.

## Quick start

**Endpoint (streamable HTTP, no auth):**

```
https://ndis-provider-feed-125475360011.australia-southeast1.run.app/mcp
```

This is an MCP endpoint, not a web page. Opening it in a browser shows a "Bad Request" error. That's expected.

**Claude Code:**

```
claude mcp add --transport http ndis-provider-feed https://ndis-provider-feed-125475360011.australia-southeast1.run.app/mcp
```

**Claude Desktop / claude.ai:** add a custom connector with the endpoint URL above.

**Any other MCP client:** point it at the endpoint URL using the streamable HTTP transport.

Then ask something like *"Find NDIS providers offering Supported Independent Living in Cardiff, NSW"*.

## Tools

| Tool | What it does |
|---|---|
| `search_providers` | Search by head office location and/or service category. Returns currently Approved providers by default, sorted by business name. |
| `get_provider` | Full record for one provider, by ABN. |
| `list_service_categories` | The 38 valid NDIS registration groups to use as `service_category`. |

`search_providers` parameters (all optional):

| Parameter | Match |
|---|---|
| `suburb` | Case-insensitive partial match on head office suburb |
| `state` | Exact, e.g. `NSW`, `VIC` |
| `postcode` | Exact 4-digit postcode |
| `service_category` | Exact, one of `list_service_categories()` |
| `include_revoked` | Include providers whose registration was revoked (default `false`) |
| `limit` | Max results (default `20`) |

### Example

Request:

```json
{ "tool": "search_providers",
  "arguments": { "suburb": "Cardiff", "state": "NSW", "service_category": "Supported Independent Living", "limit": 1 } }
```

Each result is a provider record like this (shortened):

```json
{
  "provider_id": "60632514455",
  "business_name": "ADRASTEIA SERVICES PTY LTD",
  "legal_name": "ADRASTEIA SERVICES PTY LTD",
  "entity_type": "organisation",
  "registration_status": "Approved",
  "registration_expiry": "2027-10-29",
  "service_categories": ["Behaviour Support", "Support Coordination", "Supported Independent Living", "..."],
  "has_registration_conditions": true,
  "website": "https://www.adrasteia.com.au",
  "head_office": { "suburb": "CARDIFF", "state": "NSW", "postcode": "2285", "country": "AU" },
  "outlets": [ { "name": "Head Office", "address": "10 Harrison Street, CARDIFF, NSW, 2285, AU", "phone": "..." } ],
  "last_verified": "2026-10-12T22:54:37Z",
  "source": { "register": "NDIS Provider Register", "licence": "CC BY 4.0 AU", "retrieved_at": "2026-10-12T22:54:37Z" }
}
```

Full field definitions are in [`schema/ndis-provider.schema.json`](schema/ndis-provider.schema.json), and the reasoning behind each mapping is in [`schema/ndis-provider-schema-notes.md`](schema/ndis-provider-schema-notes.md).

## The data

- **Source:** the [NDIS Provider Register](https://www.ndiscommission.gov.au/provider-registration/find-registered-provider) bulk CSV, published by the NDIS Quality and Safeguards Commission.
- **Coverage (13 Oct 2026):** 29,574 providers. 27,359 are currently Approved; 2,215 have had their registration revoked and are kept for history, but are only returned when you ask for them.
- **Freshness:** every record carries `last_verified`, the time it was last pulled from the register. [`feed-status.json`](feed-status.json) shows the date and counts of the latest refresh.
- **Shape:** the source has one row per outlet. Here those rows are grouped into one record per provider (ABN), with outlets nested. Where a provider's outlets list different service categories, the record includes all of them.

### Known limitations

- **Location means head office only.** It doesn't cover where a provider actually delivers services. Outlet addresses are present for only about half of outlets in the source, and service areas aren't in the register at all.
- **Registered providers only.** Unregistered providers aren't on the register, and plan-managed and self-managed participants can use them. "Not found" means "not on the register", not "not legitimate".
- **Only what the register publishes.** There are no reviews, availability, pricing or specialisations. The website is blank for about a quarter of providers.
- **Registration conditions** are a yes/no flag (`has_registration_conditions`). The source text is long and inconsistently encoded, so it isn't republished yet.
- **Results are sorted alphabetically,** not by relevance.

### Privacy

- **Sole traders:** many are registered under their own personal name. For these records (`entity_type: "individual"`), the personal legal name is withheld and only the trading name is shown. The licence would allow republishing it, but finding a provider doesn't need it.
- **What's logged:** each tool call logs a timestamp, the MCP session ID, the client's user-agent and the search parameters. Cloud Run's standard request logs also record IP addresses. Logs are used only to tell real usage apart from automated crawlers, and are deleted after 30 days.

### Corrections

This feed mirrors the official register. If a provider's details are wrong, the fix has to be made with the NDIS Commission, and it will flow through at the next weekly refresh.

## Licence and attribution

- **Code:** [MIT](LICENSE) © 2026 Ben Armstrong.
- **Data:** contains information from the NDIS Provider Register, © NDIS Quality and Safeguards Commission, used under [Creative Commons Attribution 4.0 Australia (CC BY 4.0 AU)](https://creativecommons.org/licenses/by/4.0/). The data has been restructured (grouped by provider, fields parsed, sole traders' legal names withheld). If you reuse data from this feed, keep that attribution.

## Status and feedback

This is an early-stage project, built and run by Ben Armstrong ([@benno303](https://github.com/benno303)). There's no uptime guarantee, and the endpoint scales to zero when idle, so the first call after a quiet period can take a few seconds.

I'm exploring whether there's a sustainable business in keeping provider information reliable for AI assistants. Anything paid would sit on top of this feed; the register feed itself stays free.

Feedback, bug reports and "this would be useful if…" ideas are very welcome. Please [open an issue](https://github.com/benno303/ndis-provider-feed/issues).

## Running it yourself

Requires Python 3.10+.

```
pip install -r requirements.txt

# Run locally over stdio against the bundled 10-record sample
python mcp_server/server.py

# Build the full feed from a fresh download of the register
curl -L -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" -o register.csv https://www.ndiscommission.gov.au/provider-registration/find-registered-provider/download-csv
python ingest/ingest_ndis.py register.csv mcp_server/data/ndis_providers.jsonl
python ingest/validate_feed.py mcp_server/data/ndis_providers.jsonl
python mcp_server/server.py --data mcp_server/data/ndis_providers.jsonl

# Serve over HTTP (binds 0.0.0.0, port from $PORT, default 8000)
python mcp_server/server.py --data mcp_server/data/ndis_providers.jsonl --transport streamable-http

# End-to-end check over the real MCP protocol
python mcp_server/test_server.py mcp_server/data/ndis_providers.jsonl
```

The register download is about 40 MB and takes a minute or two to generate. The Commission's server doesn't respond to non-browser user-agents (curl's default just hangs), hence the `-A` flag.

### Notes on the MCP Python SDK (2.x)

- Tools raise `ToolError` for expected failures (e.g. ABN not found), so the client gets a readable `is_error=True` result. Any other exception is treated as a server crash.
- Tools returning a list come back in `structured_content`. Tools returning a `dict` (like `get_provider`) come back as JSON text in `content[0].text`, so clients should handle both.
