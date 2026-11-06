import json
import urllib.request
from typing import Any

class LocalLLMInference:
    """Handles local inference requests routed to llama-server (e.g. running on port 8081)."""
    def __init__(self, endpoint: str = "http://127.0.0.1:8081/v1/chat/completions", model: str = "default") -> None:
        self.endpoint = endpoint
        self.model = model

    def generate(self, prompt: str, system_prompt: str = "You are an autonomous terminal agent helper.", temperature: float = 0.2, max_tokens: int = 512) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                return res_data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f"[LLM Error: {e}]"
