import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from station import editor, harness


class Resource:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        pass


def response(outputs, text="{}", status="completed"):
    return SimpleNamespace(
        output=[SimpleNamespace(model_dump=lambda mode, data=data: copy.deepcopy(data)) for data in outputs],
        output_text=text,
        status=status,
        model_dump=lambda mode: {"status": status, "output": outputs},
    )


def native_outputs():
    return [
        {"type": "function_call", "name": "task", "call_id": "task-1"},
        {"type": "function_call_output", "call_id": "task-1", "output": "Completed"},
        {"type": "shell_call_output", "output": [{"exit_code": 0}]},
    ]


def configure(monkeypatch, responses):
    monkeypatch.setenv("EDITORIAL_AGENT_NAME", "test-newsroom")
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.test/api/projects/news")
    client = SimpleNamespace(
        conversations=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(id="conversation-1"))),
        responses=SimpleNamespace(create=AsyncMock(side_effect=responses)),
    )
    project = SimpleNamespace(get_openai_client=lambda **_kwargs: Resource(client))
    monkeypatch.setattr(harness, "DefaultAzureCredential", lambda: Resource(None))
    monkeypatch.setattr(harness, "AIProjectClient", lambda **_kwargs: Resource(project))
    return client


async def test_managed_request_requires_native_execution_and_omits_unsupported_settings(monkeypatch):
    client = configure(monkeypatch, [response(native_outputs(), '{"verified":true}')])
    records = []

    async def trace(record):
        records.append(copy.deepcopy(record))

    assert await harness.run("Check facts", {"evidence": []}, trace=trace) == '{"verified":true}'
    request = client.responses.create.await_args.kwargs
    assert set(request) == {"conversation", "input"}
    assert request["conversation"] == "conversation-1"
    assert set(records[-1]["native_tools"]) == {"task", "shell"}
    assert records[-1]["agent"] == "test-newsroom"
    assert records[-1]["responses"]


async def test_native_capabilities_are_not_inferred_from_claimed_response_text(monkeypatch):
    configure(monkeypatch, [response([], '{"subagents_used":true,"shell_used":true}')])
    with pytest.raises(RuntimeError, match="actually execute"):
        await harness.run("Check facts", {})
    unresolved = [{"type": "function_call", "name": "task", "call_id": "never-completed"}]
    assert harness.native_tools(unresolved) == set()


async def test_function_tool_output_returns_to_same_conversation(monkeypatch):
    call = {"type": "function_call", "name": "collect_news", "call_id": "collect-1", "arguments": "{}"}
    client = configure(monkeypatch, [response([call]), response([], '{"done":true}')])
    execute = AsyncMock(return_value={"evidence": []})
    await harness.run("Collect", {}, handlers={"collect_news": execute}, require_native=False)
    execute.assert_awaited_once_with({})
    second = client.responses.create.await_args_list[1].kwargs
    assert second["conversation"] == "conversation-1"
    assert second["input"][0]["call_id"] == "collect-1"
    assert second["input"][0]["type"] == "function_call_output"


@pytest.mark.parametrize("name,arguments", [("unexpected_tool", "{}"), ("collect_news", '{"query":"secret"}')])
async def test_unapproved_or_parameterized_news_tools_are_rejected(monkeypatch, name, arguments):
    call = {"type": "function_call", "name": name, "call_id": "bad", "arguments": arguments}
    configure(monkeypatch, [response([call])])
    execute = AsyncMock()
    with pytest.raises((RuntimeError, ValueError)):
        await harness.run("Collect", {}, handlers={"collect_news": execute}, require_native=False)
    execute.assert_not_awaited()


async def test_managed_editor_never_uses_direct_model_path(monkeypatch):
    monkeypatch.setenv("EDITORIAL_AGENT_NAME", "test-newsroom")
    generate = AsyncMock(return_value='{"brief":true}')
    monkeypatch.setattr(harness, "generate", generate)
    assert await editor._response("Facts only", {"evidence": []}, {"type": "object"}, 10000) == '{"brief":true}'
    generate.assert_awaited_once()


async def test_research_adapter_fails_when_the_agent_skips_it(monkeypatch):
    configure(monkeypatch, [response([], '{"done":true}')])
    with pytest.raises(RuntimeError, match="did not execute"):
        await harness.research("collect")
