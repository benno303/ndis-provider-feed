#!/usr/bin/env python3
"""End-to-end check: spawns server.py as a real subprocess over stdio and
drives it with the official MCP client SDK — the same path a real agent
client (Claude Desktop/Code, or any MCP-speaking agent) would use. This is
deliberately not a call into build_server() in-process: an earlier version
of this script did that, and it hid a real behavioural difference (see
README note on ToolError) that only shows up over the actual protocol.

Run manually: python mcp_server/test_server.py <data.jsonl>
Not a formal test suite (no assertions framework) — a build-verification
script for Phase 0, per the plan's "verify, don't assume" principle.
"""

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from server import DEFAULT_DATA_PATH

SERVER_SCRIPT = Path(__file__).resolve().parent / "server.py"


def extract_result(result):
    """Real MCP client-side handling: prefer structured_content when the
    server provided it (list/primitive returns), otherwise fall back to
    parsing the JSON text content (what a plain `dict` return comes back
    as in this SDK version — see server.py's get_provider for why)."""
    if result.structured_content is not None:
        content = result.structured_content
        return content["result"] if isinstance(content, dict) and "result" in content else content
    import json

    return json.loads(result.content[0].text)


async def run_checks(data_path: Path):
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_SCRIPT), "--data", str(data_path)],
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = (await session.list_tools()).tools
            print(f"Registered tools: {[t.name for t in tools]}")
            assert {"search_providers", "get_provider", "list_service_categories"} <= {
                t.name for t in tools
            }

            result = await session.call_tool("list_service_categories", {})
            categories = extract_result(result)
            print(f"list_service_categories: {len(categories)} categories, isError={result.is_error}")
            assert len(categories) == 38, f"expected 38 categories, got {len(categories)}"

            result = await session.call_tool("search_providers", {"state": "VIC", "limit": 5})
            hits = extract_result(result)
            print(f"search_providers(state=VIC): {len(hits)} results, isError={result.is_error}")
            for h in hits:
                assert h["head_office"]["state"] == "VIC", h
                assert h["registration_status"] == "Approved", h

            result = await session.call_tool(
                "search_providers", {"service_category": "Support Coordination", "limit": 5}
            )
            hits = extract_result(result)
            print(
                f"search_providers(service_category=Support Coordination): "
                f"{len(hits)} results, isError={result.is_error}"
            )
            for h in hits:
                assert "Support Coordination" in h["service_categories"], h

            if hits:
                pid = hits[0]["provider_id"]
                result = await session.call_tool("get_provider", {"provider_id": pid})
                record = extract_result(result)
                print(f"get_provider({pid}): got {record['business_name']!r}, isError={result.is_error}")
                assert record["provider_id"] == pid

            # Real protocol behaviour check: does a ToolError raised inside the tool
            # come back as isError=True over the wire, or crash the connection?
            result = await session.call_tool("get_provider", {"provider_id": "00000000000"})
            print(f"get_provider(bad id): isError={result.is_error} (expected True)")
            assert result.is_error is True

            print("\nAll checks passed - verified over the real stdio protocol, not just in-process.")


if __name__ == "__main__":
    data_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DATA_PATH
    print(f"Testing against: {data_path}")
    asyncio.run(run_checks(data_path))
