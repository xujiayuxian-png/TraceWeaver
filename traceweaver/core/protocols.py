from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Iterator
from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: str
    timestamp: float
    seq: int
    key: str = ""
    fields: dict[str, Any] = Field(default_factory=dict)
    raw: str = ""


class SourceSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: str
    uri: str
    options: dict[str, Any] = Field(default_factory=dict)


class SourceHandle(ABC):
    kind: str
    uri: str

    @abstractmethod
    def metadata(self) -> dict[str, Any]: ...

    @abstractmethod
    def iter_records(
        self,
        *,
        filter: dict[str, Any] | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
    ) -> Iterator[Record]: ...

    @abstractmethod
    def get_records_around(self, seq: int, *, before: int = 2, after: int = 2) -> list[Record]: ...


class Source(ABC):
    kind: str

    @abstractmethod
    def ingest(self, spec: SourceSpec) -> SourceHandle: ...


class ToolSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    description: str
    parameters_schema: dict[str, Any] = Field(default_factory=dict)

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema or {"type": "object", "properties": {}},
            },
        }

    def to_mcp_tool(self) -> dict[str, Any]:
        """
        Render the spec as an MCP `tool` entry (name + description +
        inputSchema). Mirrors `to_openai_tool()` but for the Model
        Context Protocol surface used by `traceweaver.serve.mcp`.
        """
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.parameters_schema or {"type": "object", "properties": {}},
        }

    @classmethod
    def from_pydantic(cls, model: type[BaseModel], name: str, description: str) -> "ToolSpec":
        schema = model.model_json_schema()
        schema.pop("$defs", None)
        schema.pop("title", None)
        if "type" not in schema:
            schema["type"] = "object"
        return cls(name=name, description=description, parameters_schema=schema)


class ToolContext(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    extras: dict[str, Any] = Field(default_factory=dict)
    source_handle: Any | None = None
    scope: Any | None = None
    profile_name: str | None = None
    knowledge_store: Any | None = None


class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    data: dict[str, Any] = Field(default_factory=dict)
    refs: list[str] = Field(default_factory=list)
    truncated: bool = False


class Tool(ABC):
    spec: ToolSpec

    @abstractmethod
    def run(self, ctx: ToolContext, **kwargs: Any) -> ToolResult: ...


class Message(BaseModel):
    role: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class IntelligenceRequest(BaseModel):
    system_prompt: str
    messages: list[Message]
    tools: list[dict[str, Any]] | None = None
    response_schema: dict[str, Any] | None = None


class IntelligenceResponse(BaseModel):
    kind: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    final_text: str | None = None
    final_json: dict[str, Any] | None = None
    reasoning: str | None = None
    assistant_content: str | None = None
    total_tokens: int | None = None
    total_cost_usd: float | None = None


class Intelligence(ABC):
    @abstractmethod
    def think(self, request: IntelligenceRequest) -> IntelligenceResponse: ...


class KnowledgeHit(BaseModel):
    content: str
    title: str = ""
    score: float = 0.0


class KnowledgeStore(ABC):
    @abstractmethod
    def search(self, query: str, *, top_k: int = 5, tags: list[str] | None = None) -> list[KnowledgeHit]: ...
