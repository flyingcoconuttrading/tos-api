import json
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

class BaseAgent:
    name: str = "BaseAgent"

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def _ask_claude(self, system_prompt: str, user_prompt: str) -> dict:
        message = self.client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"error": f"{self.name} returned invalid JSON", "raw": raw}
