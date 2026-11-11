"""The public entry point: guardrails around the graph, with tracing."""

from nlagent import guardrails
from nlagent.graph import GraphConfig, build_graph, run_graph
from nlagent.llm import LLMClient
from nlagent.runs import AgentRun
from nlagent.tracing import emit_trace


class Agent:
    def __init__(
        self,
        llm: LLMClient,
        config: GraphConfig | None = None,
        rate_limiter: guardrails.RateLimiter | None = None,
    ):
        self._llm = llm
        self._graph = build_graph(llm, config)
        self._rate_limiter = rate_limiter or guardrails.RateLimiter()

    def ask(self, question: str, user_id: str = "anonymous") -> AgentRun:
        if not self._rate_limiter.allow(user_id):
            return AgentRun(question=question, status="rate_limited",
                            answer="Too many questions. Please wait a moment and try again.")

        decision = guardrails.check_input(question)
        if not decision.allowed:
            return AgentRun(question=question, status="blocked", answer=decision.reason)

        run = run_graph(self._graph, question)

        output_decision = guardrails.check_output(run.answer)
        if not output_decision.allowed:
            run.status, run.answer = "blocked", output_decision.reason
        emit_trace(run, user_id=user_id, model=self._llm.model)
        return run
