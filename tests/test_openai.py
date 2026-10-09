import json
from unittest.mock import patch

import pytest

from jarvis.agents.model_errors import ModelNotConfigured
from jarvis.agents.openai import ModelStatus, OpenAIChatRouter
from jarvis.schemas import ChatMessage


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit):
        return json.dumps(self.body).encode("utf-8")


def test_openai_router_sends_history_and_parses_natural_answer():
    response = FakeResponse(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "decision": "answer",
                                "action": None,
                                "response": "Sure — what would you like to work on?",
                            }
                        )
                    }
                }
            ]
        }
    )
    with patch("jarvis.agents.openai.urlopen", return_value=response) as urlopen:
        router = OpenAIChatRouter("test-secret", "gpt-test")
        intent = router.classify(
            "Can you help me?",
            [ChatMessage(role="user", content="Hello"), ChatMessage(role="assistant", content="Hi!")],
        )

    assert intent.response == "Sure — what would you like to work on?"
    request = urlopen.call_args.args[0]
    assert request.full_url == "https://api.openai.com/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer test-secret"
    payload = json.loads(request.data)
    assert payload["messages"][-3:] == [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi!"},
        {"role": "user", "content": "Can you help me?"},
    ]


def test_openai_router_requires_key_and_reports_configured_status():
    router = OpenAIChatRouter(None, "gpt-test")
    assert router.status() == ModelStatus(False, False, "gpt-test", False)
    with pytest.raises(ModelNotConfigured, match="OPENAI_API_KEY"):
        router.classify("Hi")


def test_openai_model_status_checks_model_endpoint():
    response = FakeResponse({"id": "gpt-test"})
    with patch("jarvis.agents.openai.urlopen", return_value=response) as urlopen:
        status = OpenAIChatRouter("test-secret", "gpt-test").status()
    assert status == ModelStatus(True, True, "gpt-test", True)
    assert urlopen.call_args.args[0].full_url.endswith("/models/gpt-test")
