"""The agent as a LangGraph state machine.

    classify --> clarify          (ambiguous: ask the user a question, then stop)
             --> refuse           (out of scope)
             --> retrieve --> generate --> execute --> synthesise
                                  ^           |
                                  +-- repair <+  (on SQL error, up to max_retries times)
"""

import operator
import time
from dataclasses import dataclass
from functools import wraps
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from nlagent import steps
from nlagent.config import settings
from nlagent.db import QueryError, QueryResult, UnsafeSQLError, run_query
from nlagent.llm import LLMClient
from nlagent.retrieval import RetrievalMode, render_schema, retrieve_columns
from nlagent.runs import AgentRun
from nlagent.steps import Usage


class AgentState(TypedDict, total=False):
    question: str
    intent: str
    clarification: str
    schema: str
    columns: list[str]
    sql: str
    result: QueryResult
    error: str
    retries: int
    answer: str
    status: str
    usage: Usage
    trace: Annotated[list[dict], operator.add]  # every node appends one entry


@dataclass(frozen=True)
class GraphConfig:
    retrieval: RetrievalMode = "hybrid_rerank"
    few_shot: bool = True
    max_retries: int = settings.max_repair_retries
    classify: bool = True


def traced(name: str):
    """Wrap a node so its latency and a small detail record land in state['trace']."""

    def decorate(node):
        @wraps(node)
        def wrapper(state: AgentState) -> dict:
            started = time.perf_counter()
            update = node(state)
            detail = update.pop("detail", {})
            entry = {"node": name, "latency_s": round(time.perf_counter() - started, 4), **detail}
            return {**update, "trace": [entry]}

        return wrapper

    return decorate


def build_graph(llm: LLMClient, config: GraphConfig | None = None):
    config = config or GraphConfig()
    @traced("classify")
    def classify(state: AgentState) -> dict:
        if not config.classify:
            return {"intent": "data_question"}
        parsed, response = steps.classify_intent(llm, state["question"])
        state["usage"].add("classify", response)
        return {
            "intent": parsed["intent"],
            "clarification": parsed["clarification"],
            "detail": {"intent": parsed["intent"], "tokens_in": response.input_tokens,
                       "tokens_out": response.output_tokens},
        }

    @traced("clarify")
    def clarify(state: AgentState) -> dict:
        question = state.get("clarification") or "Could you tell me more about what you want to know?"
        return {"status": "clarification", "answer": question}

    @traced("refuse")
    def refuse(state: AgentState) -> dict:
        message = ("I can only answer questions about Formula 1 results, drivers, teams, circuits "
                   "and standings, and I cannot change data.")
        return {"status": "refused", "answer": message}

    @traced("retrieve")
    def retrieve(state: AgentState) -> dict:
        columns = retrieve_columns(state["question"], config.retrieval)
        keys = [c.key for c in columns]
        return {"schema": render_schema(columns), "columns": keys,
                "detail": {"mode": config.retrieval, "columns": len(keys)}}

    @traced("generate")
    def generate(state: AgentState) -> dict:
        sql, response = steps.generate_sql(llm, state["question"], state["schema"], config.few_shot)
        state["usage"].add("generate_sql", response)
        return {"sql": sql, "detail": {"sql": sql, "tokens_in": response.input_tokens,
                                       "tokens_out": response.output_tokens}}

    @traced("execute")
    def execute(state: AgentState) -> dict:
        try:
            result = run_query(state["sql"])
        except (QueryError, UnsafeSQLError) as error:
            return {"error": str(error), "detail": {"error": str(error)}}
        return {"result": result, "error": "", "detail": {"rows": len(result.rows)}}

    @traced("repair")
    def repair(state: AgentState) -> dict:
        sql, response = steps.repair_sql(
            llm, state["question"], state["schema"], state["sql"], state["error"]
        )
        state["usage"].add("repair_sql", response)
        return {"sql": sql, "retries": state.get("retries", 0) + 1,
                "detail": {"sql": sql, "tokens_in": response.input_tokens,
                           "tokens_out": response.output_tokens}}

    @traced("synthesise")
    def synthesise(state: AgentState) -> dict:
        answer, response = steps.synthesise_answer(llm, state["question"], state["sql"], state["result"])
        state["usage"].add("synthesise", response)
        return {"answer": answer, "status": "answered",
                "detail": {"tokens_in": response.input_tokens, "tokens_out": response.output_tokens}}

    @traced("give_up")
    def give_up(state: AgentState) -> dict:
        return {"status": "failed", "answer": "I could not produce a working query for that question."}

    def route_after_classify(state: AgentState) -> str:
        return {"ambiguous": "clarify", "out_of_scope": "refuse"}.get(state["intent"], "retrieve")

    def route_after_execute(state: AgentState) -> str:
        if not state.get("error"):
            return "synthesise"
        return "repair" if state.get("retries", 0) < config.max_retries else "give_up"

    graph = StateGraph(AgentState)
    for name, node in [("classify", classify), ("clarify", clarify), ("refuse", refuse),
                       ("retrieve", retrieve), ("generate", generate), ("execute", execute),
                       ("repair", repair), ("synthesise", synthesise), ("give_up", give_up)]:
        graph.add_node(name, node)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges("classify", route_after_classify,
                                {"clarify": "clarify", "refuse": "refuse", "retrieve": "retrieve"})
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", "execute")
    graph.add_conditional_edges("execute", route_after_execute,
                                {"synthesise": "synthesise", "repair": "repair", "give_up": "give_up"})
    graph.add_edge("repair", "execute")
    for terminal in ("clarify", "refuse", "synthesise", "give_up"):
        graph.add_edge(terminal, END)
    return graph.compile()


def run_graph(compiled_graph, question: str) -> AgentRun:
    started = time.perf_counter()
    usage = Usage()
    final = compiled_graph.invoke({"question": question, "usage": usage, "retries": 0, "trace": []})
    return AgentRun(
        question=question,
        status=final.get("status", "failed"),
        sql=final.get("sql", ""),
        result=final.get("result"),
        answer=final.get("answer", ""),
        error=final.get("error", ""),
        retries=final.get("retries", 0),
        intent=final.get("intent", ""),
        retrieved_columns=final.get("columns", []),
        usage=usage,
        trace=final["trace"],
        total_latency_s=time.perf_counter() - started,
    )
