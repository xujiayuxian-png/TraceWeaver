"""RecordReplayIntelligence: record and replay LLM interactions."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from traceweaver.core.protocols import Intelligence, IntelligenceRequest, IntelligenceResponse, Message, ToolCall


class RecordReplayIntelligence(Intelligence):
    def __init__(self, inner: Intelligence | None, recording_path: Path, mode: str):
        self.inner = inner
        self.path = recording_path
        self.mode = mode  # "record", "replay", "passthrough"
        self._recording: list[dict[str, Any]] = []
        self._idx = 0
        if mode == "replay" and recording_path.exists():
            import yaml
            self._recording = yaml.safe_load(recording_path.read_text()) or []

    def think(self, request: IntelligenceRequest) -> IntelligenceResponse:
        if self.mode == "replay":
            if self._idx >= len(self._recording):
                raise IndexError(f"Recording exhausted at turn {self._idx}")
            turn = self._recording[self._idx]
            self._idx += 1
            resp = turn["response"]
            return IntelligenceResponse(
                kind=resp["kind"],
                tool_calls=[ToolCall(**tc) for tc in resp.get("tool_calls", [])],
                final_text=resp.get("final_text"),
                final_json=resp.get("final_json"),
                reasoning=resp.get("reasoning"),
            )

        # record or passthrough
        if self.inner is None:
            raise RuntimeError("No inner intelligence provided for record/passthrough mode")

        resp = self.inner.think(request)

        if self.mode == "record":
            self._recording.append({
                "request": {
                    "system_prompt": request.system_prompt,
                    "messages": [m.model_dump() for m in request.messages],
                },
                "response": resp.model_dump(),
            })
            import yaml
            self.path.write_text(yaml.safe_dump(self._recording))

        return resp
