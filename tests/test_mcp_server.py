"""Start the MCP server as a real subprocess and talk to it over stdio, as Claude Code would."""

import asyncio
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.db


async def call_tools():
    # The client passes only a minimal environment by default, so hand over the database settings.
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "nlagent.mcp_server"], env=dict(os.environ)
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        good = await session.call_tool("run_sql", {"sql": "select name from driver order by total_race_wins desc limit 1"})
        blocked = await session.call_tool("run_sql", {"sql": "drop table driver"})
        return [t.name for t in tools.tools], good.content[0].text, blocked.content[0].text


def test_tools_are_listed_and_run_sql_is_read_only():
    names, good, blocked = asyncio.run(call_tools())

    assert set(names) == {"ask_f1", "run_sql", "describe_schema"}
    assert "Lewis Hamilton" in good
    assert blocked.startswith("Query rejected")
