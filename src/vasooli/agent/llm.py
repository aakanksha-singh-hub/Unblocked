"""Thin LLM client. Provider-agnostic, JSON-only, no framework.

Groq, Gemini and Fireworks are all reachable over an OpenAI-compatible chat
completions endpoint (Gemini via its OpenAI compatibility layer), so one client
covers all three and the provider is a config value rather than a code path.

Deliberately not using a framework. The whole surface needed here is: send
messages, get JSON back, retry on transient failures, never raise into the
caller's hot loop. An agent framework would add abstraction over four HTTP calls
and make the failure modes harder to see.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

ENDPOINTS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "fireworks": "https://api.fireworks.ai/inference/v1/chat/completions",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
}

KEY_ENV = {
    "groq": "GROQ_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "gemini": "GOOGLE_API_KEY",
}

#: Verified against each provider's live /models listing rather than assumed.
#: The first attempt used a model name that no longer exists and failed with a
#: bare 404, which is a good argument for checking rather than trusting memory.
DEFAULT_MODEL = {
    "groq": "openai/gpt-oss-120b",
    "fireworks": "accounts/fireworks/models/qwen3p7-plus",
    "gemini": "gemini-2.0-flash",
}


class LLMUnavailable(RuntimeError):
    """Raised at construction when no usable provider is configured.

    Separate from request failures on purpose: a missing key is a setup problem
    the caller should see immediately, while a failed request mid-run must
    degrade to abstention rather than crash a 180-day simulation.
    """


@dataclass
class LLMClient:
    provider: str
    model: str
    api_key: str
    timeout: float = 45.0
    max_retries: int = 3

    @classmethod
    def from_env(cls, provider: str | None = None, model: str | None = None) -> LLMClient:
        provider = (provider or os.environ.get("LLM_PROVIDER") or "groq").lower()
        if provider not in ENDPOINTS:
            raise LLMUnavailable(f"Unknown provider {provider!r}. One of: {sorted(ENDPOINTS)}")
        key = os.environ.get(KEY_ENV[provider], "")
        if not key:
            raise LLMUnavailable(f"{KEY_ENV[provider]} is not set for provider {provider!r}.")
        return cls(
            provider=provider,
            model=model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL[provider],
            api_key=key,
        )

    def complete_json(
        self, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 900
    ) -> dict[str, Any]:
        """One JSON-returning call. Raises on exhausted retries.

        temperature 0 by default: this is an extraction task with a right answer,
        and run-to-run variation in a measured pipeline is noise we can simply
        decline to introduce.
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    r = client.post(ENDPOINTS[self.provider], json=payload, headers=headers)
                if r.status_code == 429 or r.status_code >= 500:
                    # Rate limits and server errors are worth waiting out; a 400
                    # is our bug and retrying it just wastes the quota.
                    time.sleep(1.5 * (2**attempt))
                    last = RuntimeError(f"{r.status_code}: {r.text[:200]}")
                    continue
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                return json.loads(content)
            except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
                last = e
                time.sleep(1.0 * (2**attempt))
        raise RuntimeError(f"LLM call failed after {self.max_retries} attempts: {last}")

    def available_models(self) -> list[str]:
        """Ask the provider what it actually serves. Model names churn."""
        url = ENDPOINTS[self.provider].replace("/chat/completions", "/models")
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(url, headers={"Authorization": f"Bearer {self.api_key}"})
        r.raise_for_status()
        return sorted(m["id"] for m in r.json().get("data", []))

    def ping(self) -> tuple[bool, str]:
        try:
            # Generous token budget: reasoning models spend tokens before
            # emitting anything, and a 40-token ceiling made this return a bare
            # 400 while real extraction calls succeeded - a health check that
            # reported the service as down while it was up.
            out = self.complete_json(
                "Reply with JSON only.", 'Return {"ok": true}.', max_tokens=512
            )
            return bool(out.get("ok")), f"{self.provider}/{self.model}"
        except Exception as e:  # noqa: BLE001 - diagnostic path, report anything
            return False, f"{self.provider}/{self.model}: {e}"
