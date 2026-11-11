from kemudi_ai.llm import LLMError


class FakeLLM:
    """Replies from a script per purpose; an Exception instance is raised."""

    def __init__(self, responses: dict[str, list]):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.calls: list[tuple[str, str, str]] = []

    def json(self, purpose: str, system: str, user: str) -> dict:
        self.calls.append((purpose, system, user))
        queue = self.responses.get(purpose) or []
        if not queue:
            raise LLMError(f"FakeLLM has no reply for {purpose}")
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
