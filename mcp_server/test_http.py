#!/usr/bin/env python3
"""Quick check that the server responds correctly over streamable-http,
the transport used for Cloud Run. Assumes a server is already running
(see README) — this just connects as a client would.

Usage: python test_http.py http://localhost:8123/mcp
"""

import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main(url: str):
    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            print(f"Registered tools: {[t.name for t in tools]}")

            result = await session.call_tool("search_providers", {"state": "NSW", "limit": 3})
            content = result.structured_content
            hits = content["result"] if isinstance(content, dict) and "result" in content else json.loads(
                result.content[0].text
            )
            print(f"search_providers(state=NSW): {len(hits)} results")
            for h in hits:
                print(" -", h["business_name"], h["head_office"]["suburb"])

            print(f"isError on that call: {result.is_error}")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8123/mcp"
    asyncio.run(main(url))
