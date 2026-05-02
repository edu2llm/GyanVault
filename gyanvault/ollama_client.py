import base64
import requests
from pathlib import Path
from typing import Optional


class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen3.5:cloud"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def _post(self, endpoint: str, payload: dict) -> dict:
        url = f"{self.base_url}{endpoint}"
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def generate(self, prompt: str, system: Optional[str] = None, images: Optional[list] = None,
                 max_tokens: int = 1500, temperature: float = 0.2) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }
        if system:
            payload["system"] = system
        if images:
            payload["images"] = images
        data = self._post("/api/generate", payload)
        return data.get("response", "")

    def generate_with_image(self, image_path: Path, prompt: str,
                            max_tokens: int = 1024, temperature: float = 0.2) -> str:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        return self.generate(prompt=prompt, images=[image_b64], max_tokens=max_tokens, temperature=temperature)

    def chat(self, messages: list, fmt: Optional[str] = None,
             max_tokens: int = 4000, temperature: float = 0.2) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }
        if fmt:
            payload["format"] = fmt
        data = self._post("/api/chat", payload)
        return data.get("message", {}).get("content", "")
