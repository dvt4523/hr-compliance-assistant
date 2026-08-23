"""Siraya call layer (OpenAI-compatible). Structured output is the backbone.

Mirrors the course's `generate` / `generate_json` helpers, but against Siraya via
the openai SDK. Retry-wrapped; accumulates token usage for the eval cost metric.
"""
from __future__ import annotations

import copy
import time
from typing import Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)


def _inline_defs(schema: dict) -> dict:
    """Resolve $ref/$defs into a self-contained schema (some models don't follow $ref)."""
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                return resolve(copy.deepcopy(defs[name]))
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(x) for x in node]
        return node

    return resolve(schema)


def _strictify(node):
    """Recursively make a JSON schema strict-mode compliant (OpenAI/Siraya):
    every object gets additionalProperties:false and required=all keys; drop
    unsupported keywords (default/title)."""
    if isinstance(node, dict):
        node.pop("default", None)
        node.pop("title", None)
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
            for v in node["properties"].values():
                _strictify(v)
        for key in ("items", "anyOf", "allOf", "oneOf", "prefixItems"):
            if key in node:
                v = node[key]
                (_strictify_each(v) if isinstance(v, list) else _strictify(v))
    return node


def _strictify_each(items):
    for x in items:
        _strictify(x)


def build_strict_schema(model: Type[BaseModel]) -> dict:
    return _strictify(_inline_defs(model.model_json_schema()))


class LLMClient:
    """Thin wrapper: one retry-wrapped call + generate / generate_json helpers."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.client = OpenAI(
            api_key=api_key or config.require_key(),
            base_url=base_url or config.SIRAYA_BASE_URL,
        )
        # usage ledger: one dict per call, for the eval cost metric (Siraya's
        # `cost` field is null on our key, but token `usage` is returned).
        self.usage_log: list[dict] = []

    def _call(self, **kwargs):
        """Chat completion with a small retry (429 -> 60s, 503 -> 10s), once."""
        for attempt in range(2):
            try:
                resp = self.client.chat.completions.create(**kwargs)
                if getattr(resp, "usage", None) is not None:
                    u = resp.usage
                    self.usage_log.append(
                        {
                            "model": kwargs.get("model"),
                            "prompt_tokens": getattr(u, "prompt_tokens", 0),
                            "completion_tokens": getattr(u, "completion_tokens", 0),
                            "total_tokens": getattr(u, "total_tokens", 0),
                        }
                    )
                return resp
            except Exception as e:  # noqa: BLE001 - narrow retry, then re-raise
                status = getattr(e, "status_code", None) or getattr(e, "code", None)
                if attempt == 0 and status in (429, 503):
                    time.sleep(60 if status == 429 else 10)
                    continue
                raise

    def generate(self, prompt: str, *, model: str | None = None, system: str | None = None,
                 temperature: float = 0.0) -> str:
        """Free-text completion -> str."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self._call(
            model=model or config.CHAT_MODEL, messages=messages, temperature=temperature
        )
        return (resp.choices[0].message.content or "").strip()

    def generate_json(self, prompt: str, schema: Type[T], *, model: str | None = None,
                      system: str | None = None, temperature: float = 0.0) -> T:
        """Structured output -> an instance of `schema` (strict json_schema)."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self._call(
            model=model or config.CHAT_MODEL,
            messages=messages,
            temperature=temperature,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": build_strict_schema(schema),
                },
            },
        )
        content = resp.choices[0].message.content or "{}"
        return schema.model_validate_json(content)

    def total_tokens(self) -> int:
        return sum(u["total_tokens"] for u in self.usage_log)
