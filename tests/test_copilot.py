import json
import subprocess

import pytest

from jarvis.agents.copilot import CopilotCLIChatRouter
from jarvis.agents.model_errors import ModelInvalidResponse, ModelNotConfigured, ModelUnavailable
from jarvis.schemas import ChatMessage, OllamaIntent


def make_router(tmp_path, runner):
    executable = tmp_path / "copilot.exe"
    executable.touch()
    return CopilotCLIChatRouter(
        model="auto",
        working_directory=tmp_path,
        executable=executable,
        runner=runner,
    )


def test_copilot_cli_returns_conversational_answer_and_disables_cli_tools(tmp_path):
    response = json.dumps(
        {"decision": "answer", "action": None, "response": "Sure, what would you like to do?"}
    )
    captured = {}

    def runner(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=response, stderr="")

    router = make_router(tmp_path, runner)
    result = router.classify(
        "Can you help?",
        [ChatMessage(role="user", content="Hi"), ChatMessage(role="assistant", content="Hello!")],
    )

    assert result == OllamaIntent(
        decision="answer",
        action=None,
        response="Sure, what would you like to do?",
    )
    assert captured["args"][-1] == "--available-tools"
    assert captured["kwargs"]["cwd"] == str(tmp_path.resolve())
    prompt = captured["args"][captured["args"].index("--prompt") + 1]
    assert '"content": "Hello!"' in prompt
    assert "Return only one valid JSON object" in prompt


def test_copilot_cli_requires_installation_and_sign_in(tmp_path):
    router = CopilotCLIChatRouter("auto", tmp_path, executable=tmp_path / "missing.exe")
    with pytest.raises(ModelNotConfigured, match="copilot login"):
        router.classify("Hello")

    executable = tmp_path / "copilot.exe"
    executable.touch()
    router = CopilotCLIChatRouter(
        "auto",
        tmp_path,
        executable=executable,
        runner=lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="Please run copilot login",
            stderr="",
        ),
    )
    with pytest.raises(ModelNotConfigured, match="Sign in"):
        router.classify("Hello")


def test_copilot_cli_reports_non_auth_failures_and_timeout(tmp_path):
    executable = tmp_path / "copilot.exe"
    executable.touch()
    router = CopilotCLIChatRouter(
        "auto",
        tmp_path,
        executable=executable,
        runner=lambda *args, **kwargs: subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="network error"),
    )
    with pytest.raises(ModelUnavailable):
        router.classify("Hello")

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("copilot", timeout=90)

    router.runner = timeout
    with pytest.raises(ModelUnavailable, match="timeout"):
        router.classify("Hello")


def test_copilot_cli_retries_only_invalid_structured_output(tmp_path):
    calls = []
    valid_response = json.dumps({"decision": "answer", "action": None, "response": "Hello!"})

    def runner(args, **kwargs):
        calls.append(args)
        output = "not JSON" if len(calls) == 1 else valid_response
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=output, stderr="")

    router = make_router(tmp_path, runner)
    assert router.classify("Hello").response == "Hello!"
    assert len(calls) == 2
    assert "did not match the required schema" in calls[1][calls[1].index("--prompt") + 1]

    router.runner = lambda args, **kwargs: subprocess.CompletedProcess(
        args=args,
        returncode=0,
        stdout="still not JSON",
        stderr="",
    )
    with pytest.raises(ModelInvalidResponse, match="after one retry"):
        router.classify("Hello")


def test_copilot_cli_status_reports_installed_executable(tmp_path):
    executable = tmp_path / "copilot.exe"
    executable.touch()
    router = CopilotCLIChatRouter("auto", tmp_path, executable=executable)
    status = router.status()
    assert status.configured is True
    assert status.reachable is True
    assert status.model_available is True
    assert status.model == "auto"
