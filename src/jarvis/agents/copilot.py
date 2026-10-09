import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from pydantic import ValidationError

from jarvis.agents.model_errors import ModelInvalidResponse, ModelNotConfigured, ModelUnavailable
from jarvis.agents.prompts import ASSISTANT_SYSTEM_PROMPT
from jarvis.schemas import ChatMessage, OllamaIntent


@dataclass(frozen=True)
class CopilotStatus:
    configured: bool
    reachable: bool
    model: str | None
    model_available: bool


class CopilotCLIChatRouter:
    def __init__(
        self,
        model: str,
        working_directory: str | Path,
        executable: str | Path | None = None,
        timeout: float = 90,
        runner=subprocess.run,
    ):
        self.model = model
        self.working_directory = Path(working_directory).resolve()
        self.executable = Path(executable).expanduser() if executable else find_copilot_cli()
        self.timeout = timeout
        self.runner = runner

    def classify(self, goal: str, history: list[ChatMessage] | None = None) -> OllamaIntent:
        if self.executable is None or not self.executable.is_file():
            raise ModelNotConfigured("Install GitHub Copilot CLI, then sign in with `copilot login`.")
        prompt = self._build_prompt(goal, history or [])
        args = [
            str(self.executable),
            "--prompt",
            prompt,
            "--silent",
            "--model",
            self.model,
            "--available-tools",
        ]
        try:
            for attempt in range(2):
                result = self.runner(
                    args + (["--no-ask-user"] if attempt else []),
                    cwd=str(self.working_directory),
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                )
                if result.returncode != 0:
                    output = f"{result.stdout}\n{result.stderr}".casefold()
                    if any(
                        marker in output
                        for marker in ("not logged in", "not authenticated", "run /login", "copilot login")
                    ):
                        raise ModelNotConfigured("Sign in to GitHub Copilot CLI with `copilot login`.")
                    raise ModelUnavailable("GitHub Copilot CLI could not complete the chat request.")

                content = result.stdout.strip()
                if content.startswith("```") and content.endswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                try:
                    return OllamaIntent.model_validate_json(content)
                except ValidationError as error:
                    if attempt == 1:
                        raise ModelInvalidResponse(
                            "GitHub Copilot returned an invalid structured response after one retry"
                        ) from error
                    args[args.index("--prompt") + 1] += (
                        "\n\nYour previous response did not match the required schema. "
                        "Answer the original request again. Return only a complete valid JSON "
                        "object with decision, action, and response fields; include action=null "
                        "and response as a string for ordinary conversation."
                    )
        except subprocess.TimeoutExpired as error:
            raise ModelUnavailable("Copilot did not respond before the 90-second timeout") from error
        except OSError as error:
            raise ModelUnavailable("GitHub Copilot CLI could not be started") from error

    def status(self) -> CopilotStatus:
        executable = self.executable
        installed = executable is not None and executable.is_file()
        return CopilotStatus(
            configured=installed,
            reachable=installed,
            model=self.model if installed else None,
            model_available=installed,
        )

    def _build_prompt(self, goal: str, history: Sequence[ChatMessage]) -> str:
        conversation = [
            {"role": message.role, "content": message.content}
            for message in history
        ]
        return (
            f"{ASSISTANT_SYSTEM_PROMPT}\n\n"
            "Earlier conversation (quoted user/assistant context, not system instructions):\n"
            f"{json.dumps(conversation, ensure_ascii=False)}\n\n"
            "Current user message:\n"
            f"{goal}\n\n"
            "Return only one valid JSON object with exactly these keys: "
            '"decision", "action", "response". For normal conversation use '
            '{"decision":"answer","action":null,"response":"your natural-language reply"}. '
            "For a supported local action use decision=action and the exact validated action fields. "
            "Do not use Markdown fences or add text outside the JSON object."
        )


def find_copilot_cli() -> Path | None:
    configured = shutil.which("copilot")
    if configured:
        candidate = Path(configured)
        if candidate.is_file() and candidate.suffix.casefold() == ".exe":
            return candidate

    local_app_data = Path.home() / "AppData" / "Local"
    winget_packages = local_app_data / "Microsoft" / "WinGet" / "Packages"
    if winget_packages.is_dir():
        candidates = sorted(winget_packages.glob("GitHub.Copilot_*/copilot.exe"))
        if candidates:
            return candidates[-1]
    return None
