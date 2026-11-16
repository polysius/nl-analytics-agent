"""MCP server that exposes the agent to Claude Code, Cursor and other MCP clients.

Run over stdio:  python -m nlagent.mcp_server
The server follows AGENT_DOMAIN: the F1 server is `f1-analytics` with `ask_f1`, the taxi server
is `taxi-analytics` with `ask_taxi`.

Tools:
  ask_f1         Ask a question in plain English. Needs an LLM key.
  run_sql        Run one read-only SELECT directly. No LLM involved.
  describe_schema  Show the schema the agent would use for a question. No LLM involved.
"""

from mcp.server.mcpserver import MCPServer

from nlagent.agent import Agent
from nlagent.db import QueryError, UnsafeSQLError, run_query
from nlagent.domains import active_domain
from nlagent.llm import get_llm
from nlagent.retrieval import render_schema, retrieve_columns
from nlagent.steps import format_result

domain = active_domain()
mcp = MCPServer(f"{domain.name}-analytics")
_agent: Agent | None = None


def _get_agent() -> Agent:
    """Create the agent on first use, so tools that need no LLM work without a key."""
    global _agent
    if _agent is None:
        _agent = Agent(get_llm())
    return _agent


@mcp.tool(name=f"ask_{domain.name}", description=f"Answer a question about {domain.subject}.")
def ask(question: str) -> str:
    run = _get_agent().ask(question, user_id="mcp")
    if run.status != "answered":
        return f"[{run.status}] {run.answer}"
    return f"{run.answer}\n\nSQL:\n{run.sql}"


@mcp.tool(description="Run one read-only SELECT query against the database (row cap and timeout apply).")
def run_sql(sql: str) -> str:
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
