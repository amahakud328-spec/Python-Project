"""Optional OpenAI-compatible AI writing assistant; no provider is assumed."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AIConfigurationError(RuntimeError):
    """Raised when the AI provider has not been configured."""


class AIRequestError(RuntimeError):
    """Raised when an AI service cannot fulfill a request."""


PROMPTS = {
    "Correct grammar": "Correct grammar and spelling without changing the meaning.",
    "Improve writing": "Improve clarity, flow, and sentence quality while preserving meaning.",
    "Rewrite selected text": "Rewrite the text clearly and naturally while preserving its meaning.",
    "Summarize": "Summarize the text into its key points, using concise language.",
    "Explain difficult words": "Explain difficult words in this text in simple language.",
    "Generate paragraph": "Write one concise, informative paragraph about this topic.",
}


class WritingAssistant:
    """Calls an explicitly configured local or hosted OpenAI-compatible endpoint."""

    def __init__(self) -> None:
        self.base_url = os.environ.get("SMARTPAD_AI_BASE_URL", "").strip()
        self.model = os.environ.get("SMARTPAD_AI_MODEL", "").strip()
        self.api_key = os.environ.get("SMARTPAD_AI_API_KEY", "").strip()

    @staticmethod
    def setup_instructions() -> str:
        return (
            "AI writing is optional. Configure an OpenAI-compatible endpoint before use:\n\n"
            "SMARTPAD_AI_BASE_URL (for example, http://localhost:11434/v1)\n"
            "SMARTPAD_AI_MODEL (for example, a model installed in Ollama)\n"
            "SMARTPAD_AI_API_KEY (optional for local providers; required by some hosted APIs)\n\n"
            "Restart SmartPad after setting these environment variables. Text is sent to "
            "the configured provider only when you choose an AI action."
        )

    def run(self, action: str, text: str) -> str:
        if not self.base_url or not self.model:
            raise AIConfigurationError(self.setup_instructions())
        if action not in PROMPTS:
            raise ValueError("Choose a supported writing action.")
        if not text.strip():
            raise ValueError("Select text or enter a topic first.")

        url = self.base_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": PROMPTS[action]},
                {"role": "user", "content": text},
            ],
            "temperature": 0.4,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        try:
            with urlopen(request, timeout=45) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise AIRequestError(f"AI provider returned HTTP {error.code}.") from error
        except (URLError, TimeoutError, OSError) as error:
            raise AIRequestError(f"Could not reach the configured AI provider: {error}") from error
        except (UnicodeError, json.JSONDecodeError) as error:
            raise AIRequestError("The AI provider returned an invalid response.") from error
        try:
            answer = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise AIRequestError("The AI provider response did not contain generated text.") from error
        if not isinstance(answer, str) or not answer.strip():
            raise AIRequestError("The AI provider returned an empty response.")
        return answer.strip()
