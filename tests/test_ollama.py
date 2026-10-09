import json
from unittest.mock import patch

import pytest

from jarvis.agents.ollama import OllamaIntentRouter, OllamaInvalidResponse, OllamaNotConfigured, OllamaStatus
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


def test_ollama_intent_output_is_validated_and_bound_to_known_actions():
    response = FakeResponse(
        {
            "message": {
                "content": json.dumps(
                    {
                        "decision": "action",
                        "action": {"action": "run_command", "command": "Get-Date"},
                        "response": None,
                    }
                )
            }
        }
    )
    with patch("jarvis.agents.ollama.urlopen", return_value=response) as urlopen:
        router = OllamaIntentRouter("http://127.0.0.1:11434/", "qwen2.5:3b")
        intent = router.classify("Run Get-Date")

    assert intent.action is not None
    assert intent.action.action == "run_command"
    assert intent.action.command == "Get-Date"
    assert urlopen.call_args.args[0].full_url == "http://127.0.0.1:11434/api/chat"


def test_ollama_receives_validated_conversation_history():
    response = FakeResponse(
        {
            "message": {
                "content": json.dumps(
                    {"decision": "answer", "action": None, "response": "Paris is the capital of France."}
                )
            }
        }
    )
    with patch("jarvis.agents.ollama.urlopen", return_value=response) as urlopen:
        router = OllamaIntentRouter("http://127.0.0.1:11434", "qwen2.5:3b")
        intent = router.classify(
            "What country is it in?",
            history=[
                ChatMessage(role="user", content="What is Paris?"),
                ChatMessage(role="assistant", content="Paris is the capital of France."),
            ],
        )

    assert intent.response == "Paris is the capital of France."
    sent = json.loads(urlopen.call_args.args[0].data)
    assert sent["messages"][-3:] == [
        {"role": "user", "content": "What is Paris?"},
        {"role": "assistant", "content": "Paris is the capital of France."},
        {"role": "user", "content": "What country is it in?"},
    ]


def test_ollama_rejects_unknown_or_incomplete_actions():
    response = FakeResponse(
        {
            "message": {
                "content": json.dumps(
                    {
                        "decision": "action",
                        "action": {"action": "send_email", "recipient": "someone@example.com"},
                    }
                )
            }
        }
    )
    with patch("jarvis.agents.ollama.urlopen", return_value=response):
        router = OllamaIntentRouter("http://127.0.0.1:11434", "qwen2.5:3b")
        with pytest.raises(OllamaInvalidResponse):
            router.classify("Send an email")


def test_ollama_status_and_unconfigured_state():
    response = FakeResponse({"models": [{"name": "qwen2.5:3b"}]})
    with patch("jarvis.agents.ollama.urlopen", return_value=response):
        status = OllamaIntentRouter("http://127.0.0.1:11434", "qwen2.5:3b").status()
    assert status == OllamaStatus(True, True, "qwen2.5:3b", True)

    router = OllamaIntentRouter("http://127.0.0.1:11434", None)
    assert router.status() == OllamaStatus(False, False, None, False)
    with pytest.raises(OllamaNotConfigured):
        router.classify("list my files")
