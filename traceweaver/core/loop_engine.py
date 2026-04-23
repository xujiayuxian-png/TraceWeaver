from dataclasses import dataclass, field
import time
from typing import Any

from traceweaver.core.protocols import Message


@dataclass
class LoopState:
    messages: list[Message] = field(default_factory=list)
    events: list[Any] = field(default_factory=list)
    schema_retries: int = 0
    seen_calls: dict[tuple[str, str], int] = field(default_factory=dict)
    t0: float = 0.0

    def append_message(self, msg: Message) -> None:
        self.messages.append(msg)

    def append_event(self, ev: Any) -> None:
        self.events.append(ev)


class LoopEngine:
    def create_state(self, task: Any, user_request: str) -> LoopState:
        return LoopState(
            messages=[Message(role="user", content=user_request)],
            t0=time.perf_counter(),
        )
