#!/usr/bin/env python3
"""MCP server exposing the ingested NDIS Provider Register feed to AI agents.

Data source: ingest/ingest_ndis.py output (see schema/ndis-provider.schema.json).
Source register: NDIS Quality and Safeguards Commission, licensed CC BY 4.0 AU.

Run: python mcp_server/server.py --data <path-to-ingested.jsonl>
Defaults to the bundled 10-record ingest/sample_output.jsonl for a zero-setup
smoke test — point --data at a full ingestion run for real use.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from datetime import datetime, timezone

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "ndis-provider.schema.json"
DEFAULT_DATA_PATH = Path(__file__).resolve().parent.parent / "ingest" / "sample_output.jsonl"


def load_valid_categories() -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return schema["properties"]["service_categories"]["items"]["enum"]


class ProviderStore:
    """In-memory NDIS provider data with a couple of simple indexes.

    29,441 providers (the full live register at last ingestion) easily fits in
    memory — no database needed for Phase 0. Revisit if/when this needs to scale
    past a single process or needs concurrent writers (Phase 1's provider
    self-service publishing tool).
    """

    def __init__(self, data_path: Path):
        self.providers: dict[str, dict] = {}
        self.by_state: dict[str, set[str]] = defaultdict(set)
        self.by_category: dict[str, set[str]] = defaultdict(set)

        with data_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                pid = record["provider_id"]
                self.providers[pid] = record
                state = record["head_office"].get("state")
                if state:
                    self.by_state[state].add(pid)
                for cat in record["service_categories"]:
                    self.by_category[cat].add(pid)

    def search(
        self,
        suburb: str | None = None,
        state: str | None = None,
        postcode: str | None = None,
        service_category: str | None = None,
        include_revoked: bool = False,
        limit: int = 20,
    ) -> list[dict]:
        candidates = set(self.providers.keys())

        if state:
            candidates &= self.by_state.get(state.upper(), set())
        if service_category:
            candidates &= self.by_category.get(service_category, set())

        results = []
        for pid in candidates:
            record = self.providers[pid]
            if not include_revoked and record["registration_status"] != "Approved":
                continue
            head_office = record["head_office"]
            if suburb:
                office_suburb = head_office.get("suburb")
                if not office_suburb or suburb.upper() not in office_suburb.upper():
                    continue
            if postcode and head_office.get("postcode") != postcode:
                continue
            results.append(record)

        results.sort(key=lambda r: r["business_name"])
        return results[:limit]

    def get(self, provider_id: str) -> dict | None:
        return self.providers.get(provider_id)


def log_usage(ctx: Context, tool_name: str, **params) -> None:
    """Minimal usage signal, not analytics infrastructure. Cloud Run captures
    stdout into Cloud Logging automatically, so this is queryable later
    (`gcloud logging read`) without standing up anything else. Logs the
    Mcp-Session-Id header so distinct callers can be told apart from one
    caller hitting it repeatedly — the distinction that matters when
    measuring real adoption.
    """
    headers = ctx.headers or {}
    session_id = headers.get("mcp-session-id", "unknown")
    user_agent = headers.get("user-agent", "unknown")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    params_str = ", ".join(f"{k}={v!r}" for k, v in params.items() if v is not None)
    # user_agent quoted and pipe-delimited so check_usage.py can split the line
    # reliably even though both params_str and user_agent may contain spaces.
    print(f"[usage] ts={timestamp} session={session_id} tool={tool_name} ua={user_agent!r} | {params_str}", flush=True)


def build_server(data_path: Path) -> MCPServer:
    store = ProviderStore(data_path)
    valid_categories = load_valid_categories()

    server = MCPServer(
        name="ndis-provider-register",
        description=(
            "Structured, agent-readable access to the NDIS Provider Register "
            "(source: NDIS Quality and Safeguards Commission, CC BY 4.0 AU). "
            f"Loaded {len(store.providers)} providers."
        ),
    )

    @server.tool()
    def search_providers(
        ctx: Context,
        suburb: str | None = None,
        state: str | None = None,
        postcode: str | None = None,
        service_category: str | None = None,
        include_revoked: bool = False,
        limit: int = 20,
    ) -> list[dict]:
        """Search NDIS providers by head office location and/or service category.

        Location filters match the provider's head office, not individual outlets —
        outlet addresses are inconsistently populated in the source register (~54%),
        so head office is the more reliable location signal for Phase 0.

        Args:
            suburb: Case-insensitive substring match against head office suburb.
            state: Exact match, e.g. "NSW", "VIC".
            postcode: Exact 4-digit postcode match.
            service_category: Exact match against one of the known NDIS registration
                groups — call list_service_categories() for the valid values.
            include_revoked: If false (default), only "Approved" providers are returned.
            limit: Max results to return (default 20).
        """
        log_usage(ctx, "search_providers", suburb=suburb, state=state, postcode=postcode, service_category=service_category)
        return store.search(
            suburb=suburb,
            state=state,
            postcode=postcode,
            service_category=service_category,
            include_revoked=include_revoked,
            limit=limit,
        )

    @server.tool()
    def get_provider(ctx: Context, provider_id: str) -> dict:
        """Get the full record for a single provider by its ABN (provider_id)."""
        log_usage(ctx, "get_provider", provider_id=provider_id)
        record = store.get(provider_id)
        if record is None:
            # ToolError, not ValueError: this SDK version treats a bare ValueError
            # raised from a tool body as a crash (traceback logged, model only sees
            # "Error executing tool"). ToolError is the anticipated-failure path —
            # is_error=True with this message readable by the calling model.
            raise ToolError(f"No provider found with provider_id {provider_id!r}")
        return record

    @server.tool()
    def list_service_categories(ctx: Context) -> list[str]:
        """List the valid NDIS service category values usable in search_providers()."""
        log_usage(ctx, "list_service_categories")
        return valid_categories

    return server


def main():
    parser = argparse.ArgumentParser(description="Run the NDIS provider MCP server.")
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA_PATH,
        help=f"Path to an ingested JSONL file (default: bundled sample at {DEFAULT_DATA_PATH})",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="stdio for local MCP clients (Claude Desktop/Code); streamable-http for hosting behind a public URL",
    )
    args = parser.parse_args()

    if not args.data.exists():
        print(f"Data file not found: {args.data}", file=sys.stderr)
        sys.exit(1)

    server = build_server(args.data)

    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        # Cloud Run (and most container platforms) inject the port to listen on
        # via the PORT env var and expect the process bound to 0.0.0.0, not
        # localhost. Falls back to 8000 for a plain local streamable-http test.
        port = int(os.environ.get("PORT", 8000))
        server.run(transport="streamable-http", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
