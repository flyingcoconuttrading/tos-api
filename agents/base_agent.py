import json
import threading
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

# ---------------------------------------------------------------------------
# Thread-safe global token accumulator — read by /stats
# ---------------------------------------------------------------------------
_token_lock  = threading.Lock()
_token_stats = {"total_calls": 0, "total_tokens_in": 0, "total_tokens_out": 0}


def get_token_stats() -> dict:
    with _token_lock:
        return dict(_token_stats)


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
        with _token_lock:
            _token_stats["total_calls"]     += 1
            _token_stats["total_tokens_in"] += getattr(message.usage, "input_tokens",  0)
            _token_stats["total_tokens_out"]+= getattr(message.usage, "output_tokens", 0)
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
