import json
import time
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from app.agent.contracts import ModelReply, ToolInvocation
from app.core.config import Settings


class ProviderError(Exception):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code, self.retryable = code, retryable


class Provider(Protocol):
    name: str
    model: str
    is_live: bool

    def complete(self, messages: list[dict], tools: list[dict], timeout: float) -> ModelReply: ...


class DeepSeekProvider:
    name, is_live = "deepseek", True

    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None):
        self.settings, self.model, self.transport = settings, settings.llm_model, transport

    def complete(self, messages: list[dict], tools: list[dict], timeout: float) -> ModelReply:
        cfg = self.settings
        if not cfg.llm_model or not cfg.llm_api_key.get_secret_value():
            raise ProviderError("MODEL_NOT_CONFIGURED")
        parsed = urlsplit(cfg.llm_base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ProviderError("INVALID_PROVIDER_URL")
        payload = {
            "model": cfg.llm_model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "max_tokens": cfg.llm_max_output_tokens,
            "thinking": {"type": "disabled"},
            "stream": False,
        }
        start = time.monotonic()
        try:
            with httpx.Client(
                transport=self.transport, timeout=timeout, trust_env=False, follow_redirects=False
            ) as client:
                with client.stream(
                    "POST",
                    cfg.llm_base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": "Bearer " + cfg.llm_api_key.get_secret_value()},
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        raise ProviderError(
                            f"PROVIDER_HTTP_{response.status_code}",
                            retryable=response.status_code == 429 or response.status_code >= 500,
                        )
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        if time.monotonic() - start > timeout:
                            raise ProviderError("MODEL_TIMEOUT", retryable=True)
                        raw.extend(chunk)
                        if len(raw) > 250_000:
                            raise ProviderError("MODEL_RESPONSE_TOO_LARGE")
            body = json.loads(raw)
            choice = body["choices"][0]
            if choice.get("finish_reason") not in ("stop", "tool_calls"):
                raise ProviderError("MODEL_INCOMPLETE_OUTPUT")
            message = choice["message"]
            usage = body.get("usage") or {}
            calls = [
                ToolInvocation(
                    id=call["id"], name=call["function"]["name"], arguments=call["function"]["arguments"]
                )
                for call in message.get("tool_calls") or []
            ]
            if len({call.id for call in calls}) != len(calls):
                raise ProviderError("DUPLICATE_TOOL_CALL_ID")
            return ModelReply(
                content=message.get("content") or "",
                tool_calls=calls,
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
            )
        except httpx.TimeoutException as error:
            raise ProviderError("MODEL_TIMEOUT", retryable=True) from error
        except httpx.RequestError as error:
            raise ProviderError("MODEL_UNAVAILABLE", retryable=True) from error
        except (ValueError, KeyError, IndexError, TypeError, AttributeError, ValidationError) as error:
            raise ProviderError("INVALID_MODEL_RESPONSE") from error
