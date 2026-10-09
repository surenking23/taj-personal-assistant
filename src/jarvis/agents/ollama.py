import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import ValidationError

from jarvis.agents.model_errors import ModelInvalidResponse, ModelNotConfigured, ModelUnavailable
from jarvis.agents.prompts import ASSISTANT_SYSTEM_PROMPT
from jarvis.schemas import ChatMessage, OllamaIntent


OllamaNotConfigured = ModelNotConfigured
OllamaUnavailable = ModelUnavailable
OllamaInvalidResponse = ModelInvalidResponse


@dataclass(frozen=True)
class OllamaStatus:
    configured: bool
    reachable: bool
    model: str | None
    model_available: bool


class OllamaIntentRouter:
    def __init__(self, base_url: str, model: str | None, timeout: float = 20):
        self.base_url = base_url.rstrip("/")
        self.model = model.strip() if model else None
        self.timeout = timeout

    def classify(self, goal: str, history: list[ChatMessage] | None = None) -> OllamaIntent:
        if not self.model:
            raise OllamaNotConfigured("Set OLLAMA_MODEL to enable natural-language intent routing")
        messages = [{"role": "system", "content": ASSISTANT_SYSTEM_PROMPT}]
        messages.extend(
            {"role": message.role, "content": message.content}
            for message in (history or [])
        )
        messages.append({"role": "user", "content": goal})
        body = {
            "model": self.model,
            "stream": False,
            "format": OllamaIntent.model_json_schema(),
            "options": {"temperature": 0.5},
            "messages": messages,
        }
        request = Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read(1_000_000))
            content = payload["message"]["content"]
            return OllamaIntent.model_validate_json(content)
        except HTTPError as error:
            message = f"Ollama returned HTTP {error.code}"
            raise OllamaUnavailable(message) from error
        except (URLError, TimeoutError, OSError) as error:
            raise OllamaUnavailable("Ollama is not reachable on the configured local URL") from error
        except (KeyError, TypeError, json.JSONDecodeError, ValidationError) as error:
            raise OllamaInvalidResponse("Ollama returned an invalid structured intent") from error

    def status(self) -> OllamaStatus:
        if not self.model:
            return OllamaStatus(configured=False, reachable=False, model=None, model_available=False)
        request = Request(f"{self.base_url}/api/tags", method="GET")
        try:
            with urlopen(request, timeout=min(self.timeout, 3)) as response:
                payload = json.loads(response.read(1_000_000))
            models = payload["models"]
            installed = {
                name
                for item in models
                if (name := item.get("name") or item.get("model")) is not None
            }
            return OllamaStatus(
                configured=True,
                reachable=True,
                model=self.model,
                model_available=self.model in installed,
            )
        except HTTPError:
            return OllamaStatus(configured=True, reachable=False, model=self.model, model_available=False)
        except (URLError, TimeoutError, OSError, KeyError, TypeError, json.JSONDecodeError):
            return OllamaStatus(configured=True, reachable=False, model=self.model, model_available=False)
