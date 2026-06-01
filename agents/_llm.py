"""Thin OpenAI API wrapper shared by the LLM-based agents (Diagnosis, Planner).

Stateless: every call passes full context, no conversation history. The client reads
OPENAI_API_KEY from the environment. Callers check `available()` first and degrade
gracefully when the key is missing.
"""

import os

import openai

MODEL = "gpt-4o-mini"

_client: openai.OpenAI | None = None


def available() -> bool:
    """True if an OpenAI API key is configured."""
    return bool(os.environ.get("OPENAI_API_KEY"))


def complete(system: str, prompt: str, max_tokens: int = 700) -> str:
    """Run one stateless completion and return the text. Requires available().

    A timeout is set so a slow API call can never hang the synchronous Streamlit loop.
    """
    global _client
    if _client is None:
        _client = openai.OpenAI(timeout=20.0, max_retries=1)
    resp = _client.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    return (resp.choices[0].message.content or "").strip()
