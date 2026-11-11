"""Print the agent graph as a Mermaid diagram. Used to keep docs/graph.mmd and the README in sync."""

from nlagent.graph import build_graph
from nlagent.llm import StubLLM

if __name__ == "__main__":
    print(build_graph(StubLLM(["x"])).get_graph().draw_mermaid())
