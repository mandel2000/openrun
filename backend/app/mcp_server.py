"""OpenRun as an MCP server (stdio): use the coach tools from Claude Desktop (any Claude plan,
no API cost), Gemini CLI (free with a Google account) or any MCP client.

    backend/.venv/bin/python -m app.mcp_server
    OPENRUN_URL=https://run.example.com OPENRUN_API_TOKEN=... backend/.venv/bin/python -m app.mcp_server   # remote

The same tools and evidence-based rules as the in-app coach; the client's model does the talking.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from sqlmodel import Session

from .ai import coach
from .db import engine, init_db
from .tenancy import as_user


def _instructions() -> str:
    return coach.SYSTEM.format(today=dt.date.today().strftime("%A %d/%m/%Y"), language=coach.language_name())


async def list_tools(ctx, params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=[
        types.Tool(name=t["name"], description=t["description"], inputSchema=t["input_schema"]) for t in coach.TOOLS
    ])


REMOTE_URL = os.getenv("OPENRUN_URL", "").rstrip("/")  # e.g. https://run.example.com (OpenRun on a server)
REMOTE_TOKEN = os.getenv("OPENRUN_API_TOKEN", "")


def call_remote(name: str, args: dict) -> types.CallToolResult:
    import httpx

    try:
        r = httpx.post(f"{REMOTE_URL}/api/tools/{name}", json={"args": args}, timeout=120,
                       headers={"Authorization": f"Bearer {REMOTE_TOKEN}"})
        r.raise_for_status()
        out = r.json()
    except Exception as e:  # noqa: BLE001
        return types.CallToolResult(content=[types.TextContent(text=f"Error connecting to OpenRun: {e}")], isError=True)
    if not out.get("ok"):
        return types.CallToolResult(content=[types.TextContent(text=f"Error: {out.get('error')}")], isError=True)
    return types.CallToolResult(content=[types.TextContent(text=json.dumps(out["result"], default=str, ensure_ascii=False)[:60000])])


def call(name: str, args: dict) -> types.CallToolResult:
    if REMOTE_URL:
        return call_remote(name, args)
    with as_user(int(os.getenv("OPENRUN_USER_ID", "1"))), Session(engine) as s:
        try:
            out = coach.run_tool(s, name, args or {})
            return types.CallToolResult(content=[types.TextContent(text=json.dumps(out, default=str, ensure_ascii=False)[:60000])])
        except Exception as e:  # noqa: BLE001 - report tool errors to the model
            return types.CallToolResult(content=[types.TextContent(text=f"Error: {e}")], isError=True)


async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    return await asyncio.to_thread(call, params.name, params.arguments or {})


server = Server("openrun", version="0.2", title="OpenRun – running coach",
                instructions=_instructions(), on_list_tools=list_tools, on_call_tool=call_tool)


async def main() -> None:
    if not REMOTE_URL:
        init_db()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
