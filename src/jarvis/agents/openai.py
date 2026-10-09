import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import ValidationError

from jarvis.agents.model_errors import ModelInvalidResponse, ModelNotConfigured, ModelUnavailable
from jarvis.agents.prompts import ASSISTANT_SYSTEM_PROMPT
from jarvis.schemas import ChatMessage, OllamaIntent


@dataclass(frozen=True)
class ModelStatus:
    configured: bool
    reachable: bool
    model: str | None
    model_available: bool


class OpenAIChatRouter:
    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 60,
    ):
        self.api_key = api_key.strip() if api_key else None
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def classify(self, goal: str, history: list[ChatMessage] | None = None) -> OllamaIntent:
        if not self.api_key:
            raise ModelNotConfigured("Set OPENAI_API_KEY in the server environment to enable chat")
        messages = [{"role": "system", "content": ASSISTANT_SYSTEM_PROMPT}]
        messages.extend(
            {"role": message.role, "content": message.content}
            for message in (history or [])
        )
        messages.append({"role": "user", "content": goal})
        body = {
            "model": self.model,
            "temperature": 0.5,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read(1_000_000))
            content = payload["choices"][0]["message"]["content"]
            return OllamaIntent.model_validate_json(content)
        except HTTPError as error:
            raise ModelUnavailable(f"OpenAI API returned HTTP {error.code}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise ModelUnavailable("OpenAI API could not be reached") from error
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as error:
            raise ModelInvalidResponse("OpenAI API returned an invalid structured response") from error

    def status(self) -> ModelStatus:
        if not self.api_key:
            return ModelStatus(False, False, self.model, False)
        request = Request(
            f"{self.base_url}/models/{quote(self.model, safe='')}",
            headers={"Authorization": f"Bearer {self.api_key}"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=min(self.timeout, 5)) as response:
                payload = json.loads(response.read(1_000_000))
            available = payload.get("id") == self.model
            return ModelStatus(True, True, self.model, available)
        except HTTPError as error:
            return ModelStatus(True, error.code not in (401, 403, 404), self.model, False)
        except (URLError, TimeoutError, OSError, TypeError, json.JSONDecodeError):
            return ModelStatus(True, False, self.model, False)
