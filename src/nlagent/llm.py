"""One small interface over the LLM providers, so the pipeline never imports an SDK directly."""

import time
from dataclasses import dataclass
from typing import Protocol

from nlagent.config import settings


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse: ...


# Dollars per million tokens (input, output). Used only for the cost column in reports.
PRICE_PER_MTOK = {
    "claude-sonnet-5-5": (3.0, 15.0),
    "claude-haiku-5-5": (1.0, 5.0),
    "claude-opus-5-5": (5.0, 25.0),
    # Estimate used only to enforce spend caps. Check Google's price page for the real rate.
    "gemini-3-flash-preview": (0.50, 3.00),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICE_PER_MTOK.get(model, (0.0, 0.0))
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


REASONING_HEADROOM_TOKENS = 4096


class AnthropicClient:
    def __init__(self, model: str, api_key: str):
        import anthropic

        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        started = time.perf_counter()
        message = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in message.content if block.type == "text")
        return LLMResponse(
            text=text,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            latency_s=time.perf_counter() - started,
        )


class OpenAICompatClient:
    """Any server that speaks the OpenAI chat API, such as a local proxy or Ollama."""

    def __init__(self, model: str, api_key: str, base_url: str):
        import openai

        self.model = model
        self._client = openai.OpenAI(
            api_key=api_key or "unused",
            base_url=base_url or None,
            max_retries=8,  # free-tier endpoints often answer 429 or 503 under load
            timeout=60,
        )

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        started = time.perf_counter()
        completion = self._client.chat.completions.create(
            model=self.model,
            # Reasoning models spend hidden "thinking" tokens from this same budget, so a tight
            # limit cuts the visible answer off mid-word. Add headroom for the thinking.
            max_tokens=max_tokens + REASONING_HEADROOM_TOKENS,
            temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        usage = completion.usage
        choice = completion.choices[0]
        if choice.finish_reason == "length":
            raise RuntimeError("LLM reply was cut off by the token limit; raise REASONING_HEADROOM_TOKENS.")
        input_tokens = usage.prompt_tokens if usage else 0
        # total minus prompt also counts thinking tokens, which are billed as output.
        output_tokens = (usage.total_tokens - usage.prompt_tokens) if usage else 0
        return LLMResponse(
            text=choice.message.content or "",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_s=time.perf_counter() - started,
        )


class StubLLM:
    """Returns scripted replies in order, then repeats the last one. For tests and offline runs."""

    model = "stub"

    def __init__(self, replies: list[str]):
        self._replies = replies
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> LLMResponse:
        self.calls.append((system, user))
        index = min(len(self.calls) - 1, len(self._replies) - 1)
        return LLMResponse(text=self._replies[index])


def get_llm() -> LLMClient:
    if settings.llm_provider == "anthropic":
        if not settings.llm_api_key:
            raise RuntimeError("Set ANTHROPIC_API_KEY (or LLM_API_KEY) to use the anthropic provider.")
        return AnthropicClient(settings.llm_model, settings.llm_api_key)
    if settings.llm_provider == "openai":
        return OpenAICompatClient(settings.llm_model, settings.llm_api_key, settings.llm_base_url)
    raise RuntimeError(f"Unknown LLM_PROVIDER {settings.llm_provider!r}")
