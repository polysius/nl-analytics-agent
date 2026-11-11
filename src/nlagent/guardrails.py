"""Input checks, output checks and per-user rate limits that wrap the graph.

These checks are a cheap first filter. They are not the security boundary: even if
every one is bypassed, the SQL guard, the read-only role and the read-only session
(see guard.py and db.py) still stop any write from reaching the database.
"""

import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass

MAX_QUESTION_CHARS = 500

# Phrases that try to change the agent's instructions or ask it to modify data.
INJECTION_PATTERNS = [
    r"ignore (all |any )?(the )?(previous|prior|above) (instructions|rules|prompt)",
    r"disregard (all |any )?(the )?(previous|prior|above)",
    r"(reveal|show|print|repeat) (me )?(your|the) (system )?(prompt|instructions)",
    r"you are now\b",
    r"\bact as\b.*\b(admin|root|dba|superuser)\b",
    r"\b(drop|truncate|alter)\s+(table|database|schema|role)\b",
    r"\bdelete\s+from\b",
    r"\binsert\s+into\b",
    r"\bupdate\s+\w+\s+set\b",
    r"\bgrant\s+\w+",
    r"\bset\s+(role|session)\b",
]
_INJECTION = re.compile("|".join(INJECTION_PATTERNS), flags=re.IGNORECASE)

# Strings that must never appear in an answer shown to a user.
LEAK_PATTERNS = [r"sk-[A-Za-z0-9_-]{16,}", r"postgresql://\S+:\S+@", r"You write PostgreSQL queries"]
_LEAK = re.compile("|".join(LEAK_PATTERNS))


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""


def check_input(question: str) -> Decision:
    if not question.strip():
        return Decision(False, "The question is empty.")
    if len(question) > MAX_QUESTION_CHARS:
        return Decision(False, f"Questions are limited to {MAX_QUESTION_CHARS} characters.")
    if _INJECTION.search(question):
        return Decision(False, "That request looks like an attempt to change instructions or data.")
    return Decision(True)


def check_output(answer: str) -> Decision:
    if _LEAK.search(answer):
        return Decision(False, "The answer contained text that must not be shown.")
    return Decision(True)


class RateLimiter:
    """Sliding window: at most `max_calls` per user in any `window_s` seconds."""

    def __init__(self, max_calls: int = 20, window_s: float = 60.0, clock=time.monotonic):
        self._max_calls = max_calls
        self._window_s = window_s
        self._clock = clock
        self._calls: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, user_id: str) -> bool:
        now = self._clock()
        calls = self._calls[user_id]
        while calls and now - calls[0] > self._window_s:
            calls.popleft()
        if len(calls) >= self._max_calls:
            return False
        calls.append(now)
        return True
