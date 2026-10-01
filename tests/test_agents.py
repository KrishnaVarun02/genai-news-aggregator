import json
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI

from news_aggregator.agents import AgentError, OpenAIAgent
from news_aggregator.domain import SummaryOutput


def test_spending_and_key_gates():
    with pytest.raises(AgentError, match="ALLOW_PAID_API"):
        OpenAIAgent()
    with pytest.raises(AgentError, match="OPENAI_API_KEY"):
        OpenAIAgent(allow_paid=True)


def test_real_sdk_responses_structured_output_contract():
    captured = []
    output = {"title": "Fixture title", "summary": "Fixture sentence one. Fixture sentence two.", "category": "testing"}
    def transport(request):
        captured.append(json.loads(request.content))
        assert request.url.path == "/v1/responses"
        return httpx.Response(200, json={"id": "resp_fixture", "object": "response", "created_at": 0,
            "status": "completed", "error": None, "incomplete_details": None,
            "model": "gpt-4.1-mini", "output": [{"id": "msg_fixture", "type": "message", "status": "completed", "role": "assistant",
                "content": [{"type": "output_text", "text": json.dumps(output), "annotations": []}]}],
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": [], "temperature": 1, "top_p": 1, "truncation": "disabled"})
    client = OpenAI(api_key="fixture-test-only", http_client=httpx.Client(transport=httpx.MockTransport(transport)))
    agent = OpenAIAgent(client=client)
    article = SimpleNamespace(title="Fixture", url="https://example.invalid", source="fixture", content_status="description_only", content="", description="Authored input")
    result = agent.summarize(article)
    assert result == SummaryOutput(**output)
    assert captured[0]["model"] == "gpt-4.1-mini"
    assert captured[0]["text"]["format"]["type"] == "json_schema"
    assert captured[0]["text"]["format"]["strict"] is True
    assert captured[0]["store"] is False


def test_refusal_and_incomplete_output_are_errors():
    for status in ("completed", "incomplete"):
        responses = SimpleNamespace(parse=lambda **_: SimpleNamespace(status=status, output_parsed=None))
        agent = OpenAIAgent(client=SimpleNamespace(responses=responses))
        with pytest.raises(AgentError, match="refusal or incomplete"):
            agent._parse("gpt-4o-mini", "prompt", {}, SummaryOutput)


def test_error_does_not_echo_secret_request_data():
    def fail(**_):
        raise RuntimeError("sensitive-provider-body")
    agent = OpenAIAgent(client=SimpleNamespace(responses=SimpleNamespace(parse=fail)))
    with pytest.raises(AgentError) as error:
        agent._parse("gpt-4o-mini", "prompt", {}, SummaryOutput)
    assert "sensitive-provider-body" not in str(error.value)
