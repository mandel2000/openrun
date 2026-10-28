"""OpenRun as an MCP server (stdio): use the coach tools from Claude Desktop (any Claude plan,
no API cost), Gemini CLI (free with a Google account) or any MCP client.

    backend/.venv/bin/python -m app.mcp_server

The same tools and evidence-based rules as the in-app coach; the client's model does the talking.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from sqlmodel import Session

from .ai import coach
from .db import engine, init_db


def _instructions() -> str:
    return coach.SYSTEM.format(today=dt.date.today().strftime("%A %d/%m/%Y"))


async def list_tools(ctx, params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=[
        types.Tool(name=t["name"], description=t["description"], inputSchema=t["input_schema"]) for t in coach.TOOLS
    ])


def call(name: str, args: dict) -> types.CallToolResult:
    with Session(engine) as s:
        try:
            out = coach.run_tool(s, name, args or {})
            return types.CallToolResult(content=[types.TextContent(text=json.dumps(out, default=str, ensure_ascii=False)[:60000])])
        except Exception as e:  # noqa: BLE001 - report tool errors to the model
            return types.CallToolResult(content=[types.TextContent(text=f"Error: {e}")], isError=True)


async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    return await asyncio.to_thread(call, params.name, params.arguments or {})


server = Server("openrun", version="0.2", title="OpenRun – entrenador de running",
                instructions=_instructions(), on_list_tools=list_tools, on_call_tool=call_tool)


async def main() -> None:
    init_db()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
