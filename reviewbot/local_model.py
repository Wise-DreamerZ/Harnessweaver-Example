"""``fm.chat``: the ``openai.chat`` provider for local OpenAI-compatible servers
that stream unless told not to, such as ``fm serve`` (Apple's on-device
Foundation Models).

``fm serve`` answers with a server-sent event stream unless the request says
``"stream": false``, but the OpenAI client leaves ``stream`` out of a
non-streaming request, so ``openai.chat`` gets event-stream text where it
expects a completion. Its JSON Schema reader is also narrower than Pydantic's
output: it rejects ``$ref``/``$defs`` ("Undefined types"), reads a string with a
``title`` as a named enum type, and fails on regex ``pattern``s ("unsupported
pattern"). ``fm.chat`` sends ``stream: false``, inlines references and drops
titles and patterns, and is otherwise ``openai.chat``, settings included.
Dropping a tool's ``pattern`` here only changes what the model is shown: the
governor still checks every call against the manifest's full schema (step 2).
Loaded only by ``harness.fm.yaml``.
"""

_UNSUPPORTED = ("$defs", "title", "pattern")

from typing import Any

from pydantic import Field

import harnessweaver as hw
from harnessweaver_openai.chat import (
    OpenAIChat,
    OpenAIChatConfig,
    cost_from_headers,
    provider_error,
)
from harnessweaver_openai.convert import from_completion, request_kwargs

__all__ = ["LocalChat", "LocalChatConfig", "plain_schema", "plugin"]


def plain_schema(schema: Any) -> Any:
    """``schema`` with every ``$ref`` replaced by its ``$defs`` entry and no ``title``
    or ``pattern`` keys: the subset fm serve's schema reader accepts. Assumes no
    recursive types, and no property named like one of those keys."""
    defs = schema.get("$defs", {}) if isinstance(schema, dict) else {}

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {k: walk(v) for k, v in node.items() if k not in _UNSUPPORTED}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


class LocalChatConfig(OpenAIChatConfig):
    """``openai.chat``'s settings, plus room for the overlay to unset ``effort``."""

    effort: None = Field(
        default=None,
        description="Always null: harness.yaml sets effort for anthropic.messages, and the "
        "fm overlay unsets it (a null still reaches the provider's settings).",
    )


@hw.provider(
    port="ModelProvider",
    name="fm.chat",
    config=LocalChatConfig,
    deterministic=False,
    latency_class="slow",
)
class LocalChat(OpenAIChat):
    """``openai.chat`` that asks for a plain JSON completion (``stream: false``)."""

    async def generate(self, request: hw.ModelRequest, env: hw.Envelope) -> hw.ModelResponse:
        from openai import APIError

        kwargs: dict[str, Any] = request_kwargs(
            request, max_tokens_param=self.config.max_tokens_param
        )
        if "response_format" in kwargs:
            spec = kwargs["response_format"]["json_schema"]
            spec["schema"] = plain_schema(spec["schema"])
        for tool in kwargs.get("tools", []):
            tool["function"]["parameters"] = plain_schema(tool["function"]["parameters"])
        try:
            raw = await self._get_client().chat.completions.with_raw_response.create(
                **kwargs, stream=False
            )
            completion = raw.parse()
        except APIError as exc:
            raise provider_error(exc) from exc
        cost = cost_from_headers(raw.headers, self.config.cost_header)
        return self._checked(from_completion(completion, cost))


plugin = hw.Plugin(
    namespace="fm",
    version="1.0.0",
    providers=[LocalChat],
    description="openai.chat for local servers that stream by default (fm serve).",
)
