"""Minimal OpenAI-compatible tool-calling loop (works with OpenRouter).

Kept deliberately plain so results reflect the model, not clever scaffolding.
"""
from __future__ import annotations

import json
import os
import time

MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "16000"))  # per call; also caps credit reservation
MAX_NUDGES = 2  # if a turn ends with no tool call AND no valid JSON report, ask once/twice to continue
MAX_STEPS = 120  # turns, not tool calls; month-end runs need ~n_employees + retries; logged, never scored


def run(env, prompt: str, tools: list[dict], model: str, temperature: float | None = 0.0) -> tuple[str | None, list]:
    from openai import OpenAI  # imported lazily so fake-agent runs need no API key

    # Any OpenAI-compatible provider: OpenRouter (default) or e.g. Nebius Token Factory.
    base_url = os.environ.get("OPENAI_BASE_URL") or "https://openrouter.ai/api/v1"
    api_key = (os.environ.get("API_KEY") or os.environ.get("OPENROUTER_API_KEY")
               or os.environ.get("NEBIUS_API_KEY"))
    if not api_key:
        raise SystemExit("Set API_KEY (or OPENROUTER_API_KEY / NEBIUS_API_KEY) in .env")
    client = OpenAI(base_url=base_url, api_key=api_key)
    from grader.grade import parse_report
    messages: list[dict] = [{"role": "user", "content": prompt}]
    transcript: list = []
    nudges = 0
    for _ in range(MAX_STEPS):
        kwargs = {} if temperature is None else {"temperature": temperature}  # some reasoning models reject it
        if "openrouter.ai" in base_url:
            kwargs["extra_body"] = {"usage": {"include": True}}  # OpenRouter reports the exact cost per call
        resp = _create_with_retry(client, model=model, messages=messages, tools=tools,
                                  max_tokens=MAX_OUTPUT_TOKENS, **kwargs)
        msg = resp.choices[0].message
        # record the exact model/snapshot the provider actually served, for the README
        usage = resp.usage.model_dump() if getattr(resp, "usage", None) else None
        transcript.append({"served_model": resp.model, "provider": getattr(resp, "provider", None),
                           "usage": usage, **msg.model_dump(exclude_none=True)})
        if not msg.tool_calls:
            if parse_report(msg.content) is None and nudges < MAX_NUDGES:
                # Same rule for every model: a turn with neither a tool call nor the required report is
                # treated as "not finished yet", not as a final answer. Logged in the transcript.
                nudges += 1
                nudge = "Continue the task. When you are completely finished, reply with ONLY the JSON report."
                messages.append({"role": "assistant", "content": msg.content or ""})
                messages.append({"role": "user", "content": nudge})
                transcript.append({"nudge": nudges, "text": nudge})
                continue
            return msg.content, transcript
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
                result = {"error": "Arguments were not valid JSON"}
            else:
                result = env.call(tc.function.name, args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
            transcript.append({"tool": tc.function.name, "args": args, "result": result})
    return None, transcript  # step cap hit: no final report -> grader fails the claim check


def _create_with_retry(client, attempts: int = 6, **kw):
    """Retry transient provider errors (429, 5xx, in-flight budget). Out-of-credit errors still raise."""
    from openai import APIConnectionError, APIStatusError
    for i in range(attempts):
        try:
            return client.chat.completions.create(**kw)
        except APIStatusError as e:
            body = str(e)
            transient = e.status_code in (429, 500, 502, 503, 504) or "in_flight_budget" in body
            if not transient or i == attempts - 1:
                raise
            time.sleep(min(30 * (i + 1), 150))
        except APIConnectionError:
            if i == attempts - 1:
                raise
            time.sleep(15 * (i + 1))
