import os

from anthropic import Anthropic

MODEL = "claude-sonnet-5"


class Orchestrator:
    def __init__(self, api_key: str | None = None):
        self.client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def run(self, prompt: str) -> str:
        response = self.client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
