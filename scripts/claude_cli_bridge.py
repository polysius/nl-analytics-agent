"""Serve the local Claude Code CLI as an OpenAI-compatible chat endpoint.

The agent runs in a Linux container, but the `claude` CLI is installed on the host and signed in
there. This bridge lets the container use it with no code changes: set
    LLM_PROVIDER=openai  LLM_BASE_URL=http://host.docker.internal:8787/v1  LLM_MODEL=sonnet
and start the bridge on the host with `python scripts/claude_cli_bridge.py`.

Each request starts one headless `claude -p` call with no tools, no project instructions and no
saved session. Limits to know about:
- Calls count against the Claude Code plan that is signed in on this machine.
- The CLI has no temperature setting, so replies are not deterministic.
- It listens on 127.0.0.1 only. Do not expose it: anyone who can reach it can spend your plan.
"""

import json
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8787
MAX_PARALLEL_CALLS = 4
CALL_TIMEOUT_S = 180

_slots = threading.Semaphore(MAX_PARALLEL_CALLS)
_empty_dir = tempfile.mkdtemp(prefix="claude-bridge-")  # a cwd with no CLAUDE.md to load


def call_claude(model: str, system: str, user: str) -> dict:
    command = [
        "claude", "-p", "--output-format", "json", "--model", model,
        "--system-prompt", system or "You are a helpful assistant.",
        "--tools", "", "--no-session-persistence", "--disable-slash-commands",
        "--strict-mcp-config", "--setting-sources", "",
    ]
    with _slots:
        done = subprocess.run(
            command, input=user, capture_output=True, text=True, encoding="utf-8",
            timeout=CALL_TIMEOUT_S, cwd=_empty_dir, check=False,
        )
    if done.returncode != 0:
        # Headless mode reports errors (usage limits, bad input) as JSON on stdout, not stderr.
        detail = (done.stderr.strip() or done.stdout.strip())[:400]
        raise RuntimeError(f"claude exited {done.returncode}: {detail}")
    return json.loads(done.stdout)


def to_openai_response(model: str, cli_result: dict) -> dict:
    usage = cli_result.get("usage", {})
    # Cached prompt tokens are still prompt tokens as far as the cost report is concerned.
    prompt_tokens = (
        usage.get("input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
    )
    completion_tokens = usage.get("output_tokens", 0)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": cli_result.get("result", "")},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 (name fixed by BaseHTTPRequestHandler)
        if self.path.rstrip("/") == "/v1/models":
            self._send(200, {"object": "list", "data": [{"id": m, "object": "model"} for m in ("haiku", "sonnet", "opus")]})
        else:
            self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):  # noqa: N802
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._send(404, {"error": {"message": "not found"}})
            return
        request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        messages = request.get("messages", [])
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        user = "\n\n".join(m["content"] for m in messages if m["role"] != "system")
        model = request.get("model", "sonnet")
        try:
            self._send(200, to_openai_response(model, call_claude(model, system, user)))
        except Exception as error:  # report the failure to the caller instead of dropping the connection
            self._send(500, {"error": {"message": str(error), "type": "bridge_error"}})

    def log_message(self, format, *args):  # keep the console quiet during long runs
        pass


if __name__ == "__main__":
    print(f"Claude CLI bridge on http://127.0.0.1:{PORT}/v1 (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
