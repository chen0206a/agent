import json

import httpx
import pytest
from app.agent.provider import DeepSeekProvider, ProviderError
from app.agent.tools import tool_definitions
from app.core.config import Settings


def provider(handler, **overrides):
    settings = Settings(llm_model="test-model", llm_api_key="test-only-key", _env_file=None, **overrides)
    return DeepSeekProvider(settings, transport=httpx.MockTransport(handler))


def response_body(**changes):
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning_content": "this must never be persisted",
                    "tool_calls": [
                        {
                            "id": "call1",
                            "type": "function",
                            "function": {"name": "get_order", "arguments": '{"order_id":1001}'},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 15, "completion_tokens": 7},
        **changes,
    }


def test_deepseek_wire_contract_and_reasoning_exclusion():
    def handler(request):
        assert request.url == "https://api.deepseek.com/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-only-key"
        payload = json.loads(request.content)
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["tools"] and payload["stream"] is False
        return httpx.Response(200, json=response_body())

    reply = provider(handler).complete([{"role": "user", "content": "取消1001"}], tool_definitions(), 1)
    assert reply.tool_calls[0].name == "get_order"
    assert (reply.input_tokens, reply.output_tokens) == (15, 7)
    assert "reasoning_content" not in reply.model_dump_json()


@pytest.mark.parametrize(
    "status,retryable", [(401, False), (400, False), (429, True), (500, True), (302, False)]
)
def test_http_errors_are_sanitized_and_retry_classified(status, retryable):
    with pytest.raises(ProviderError) as error:
        provider(lambda _: httpx.Response(status, text="secret backend message")).complete(
            [], tool_definitions(), 1
        )
    assert error.value.code == f"PROVIDER_HTTP_{status}"
    assert error.value.retryable == retryable
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "body",
    [
        None,
        {"choices": []},
        {"choices": [{"message": {}, "finish_reason": "length"}]},
        response_body(usage={"prompt_tokens": -1}),
        response_body(usage={"prompt_tokens": True}),
    ],
)
def test_malformed_truncated_and_illegal_usage_rejected(body):
    with pytest.raises(ProviderError):
        provider(lambda _: httpx.Response(200, json=body)).complete([], tool_definitions(), 1)


def test_missing_usage_remains_unknown():
    result = provider(lambda _: httpx.Response(200, json=response_body(usage=None))).complete(
        [], tool_definitions(), 1
    )
    assert result.input_tokens is None and result.output_tokens is None


def test_network_timeout_is_sanitized():
    def handler(request):
        raise httpx.ReadTimeout("secret text", request=request)

    with pytest.raises(ProviderError) as error:
        provider(handler).complete([], tool_definitions(), 1)
    assert error.value.code == "MODEL_TIMEOUT"


@pytest.mark.parametrize(
    "url",
    ["http://api.deepseek.com", "https://key:secret@api.deepseek.com", "https://api.deepseek.com?key=secret"],
)
def test_provider_url_does_not_allow_insecure_or_embedded_credentials(url):
    with pytest.raises(ProviderError) as error:
        provider(lambda _: pytest.fail("must not request"), llm_base_url=url).complete(
            [], tool_definitions(), 1
        )
    assert error.value.code == "INVALID_PROVIDER_URL"
