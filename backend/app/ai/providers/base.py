from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Literal, TypeVar

from pydantic import BaseModel

from app.ai.router.model_router import ModelConfig, TaskType

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class RequestContext(BaseModel):
    task: TaskType
    request_id: str
    claim_id: str | None = None
    owner_id: str | None = None


class ChatResult(BaseModel):
    text: str
    model: str
    fallback_used: bool = False


class EmbeddingResult(BaseModel):
    vectors: list[list[float]]
    model: str


class StructuredResult(BaseModel):
    value: Any
    model: str
    fallback_used: bool = False


class AIError(Exception):
    def __init__(self, message: str, code: str = "provider_error", status: int | None = None,
                 retryable: bool = False):
        super().__init__(message)
        self.message, self.code, self.status, self.retryable = message, code, status, retryable


class BaseAIProvider(ABC):
    @abstractmethod
    async def chat(self, messages: list[dict], config: ModelConfig,
                   context: RequestContext) -> ChatResult: ...

    @abstractmethod
    async def structured_chat(self, messages: list[dict], schema: type[SchemaT], config: ModelConfig,
                              context: RequestContext) -> StructuredResult: ...

    @abstractmethod
    async def vision(self, prompt: str, image_data_url: str, schema: type[SchemaT],
                     config: ModelConfig, context: RequestContext) -> StructuredResult: ...

    @abstractmethod
    async def embed(self, texts: list[str], input_type: Literal["passage", "query"],
                    config: ModelConfig, context: RequestContext) -> EmbeddingResult: ...

    @abstractmethod
    async def health_check(self) -> dict: ...

    @abstractmethod
    def estimate_tokens(self, text: str) -> int: ...

    async def stream_chat(self, messages: list[dict], config: ModelConfig,
                          context: RequestContext) -> AsyncIterator[str]:
        # Buffered default lets other providers opt into a genuine SSE implementation.
        yield (await self.chat(messages, config, context)).text

    @abstractmethod
    async def close(self) -> None: ...
