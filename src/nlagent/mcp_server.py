"""MCP server that exposes the F1 agent to Claude Code, Cursor and other MCP clients.

Run over stdio:  python -m nlagent.mcp_server

Tools:
  ask_f1         Ask a question in plain English. Needs an LLM key.
  run_sql        Run one read-only SELECT directly. No LLM involved.
  describe_schema  Show the schema the agent would use for a question. No LLM involved.
"""

from mcp.server.mcpserver import MCPServer

from nlagent.agent import Agent
from nlagent.db import QueryError, UnsafeSQLError, run_query
from nlagent.llm import get_llm
from nlagent.retrieval import render_schema, retrieve_columns
from nlagent.steps import format_result

mcp = MCPServer("f1-analytics")
_agent: Agent | None = None


def _get_agent() -> Agent:
    """Create the agent on first use, so tools that need no LLM work without a key."""
    global _agent
    if _agent is None:
        _agent = Agent(get_llm())
    return _agent


@mcp.tool()
def ask_f1(question: str) -> str:
    """Answer a question about Formula 1 results, drivers, teams, circuits and standings."""
    run = _get_agent().ask(question, user_id="mcp")
    if run.status != "answered":
        return f"[{run.status}] {run.answer}"
    return f"{run.answer}\n\nSQL:\n{run.sql}"


@mcp.tool()
def run_sql(sql: str) -> str:
    """Run one read-only SELECT query against the F1 database (row cap and timeout apply)."""
    try:
        return format_result(run_query(sql))
    except (UnsafeSQLError, QueryError) as error:
        return f"Query rejected: {error}"


@mcp.tool()
def describe_schema(question: str) -> str:
    """Show the tables and columns most relevant to a question."""
    return render_schema(retrieve_columns(question, "hybrid_rerank"))


if __name__ == "__main__":
    mcp.run()
