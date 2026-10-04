import json
import uuid

from pydantic import BaseModel

from app.ai.cache import AsyncCache, cache_key
from app.ai.providers.base import BaseAIProvider, RequestContext, SchemaT, StructuredResult
from app.ai.router.model_router import NvidiaModelRouter, TaskType
from app.config import Settings


class SafetyResult(BaseModel):
    unsafe: bool
    reason: str = ""


class AIClient:
    def __init__(self, provider: BaseAIProvider, settings: Settings):
        self.provider, self.settings = provider, settings
        self.router = NvidiaModelRouter(settings)
        self.responses = AsyncCache(64 if settings.low_memory_mode else 256)

    def context(self, task: TaskType, owner_id: str, claim_id: str | None = None) -> RequestContext:
        return RequestContext(task=task, request_id=str(uuid.uuid4()), owner_id=owner_id, claim_id=claim_id)

    async def structured(self, task: TaskType, messages: list[dict], schema: type[SchemaT], owner_id: str,
                         claim_id: str | None = None, *, use_cache: bool = True) -> StructuredResult:
        config = self.router.select_model(task)
        if not use_cache:
            return await self.provider.structured_chat(messages, schema, config, self.context(task, owner_id, claim_id))
        key = cache_key(owner_id, claim_id, task, config.model_dump(), messages, schema.model_json_schema())
        return await self.responses.get_or_create(key, lambda: self.provider.structured_chat(
            messages, schema, config, self.context(task, owner_id, claim_id)))

    async def vision(self, prompt: str, image: str, schema: type[SchemaT], owner_id: str,
                     claim_id: str) -> StructuredResult:
        task = TaskType.VISION_DOCUMENT_ANALYSIS
        config = self.router.select_model(task)
        key = cache_key(owner_id, claim_id, config.model_dump(), image, schema.model_json_schema(), prompt)
        return await self.responses.get_or_create(key, lambda: self.provider.vision(
            prompt, image, schema, config, self.context(task, owner_id, claim_id)))

    async def safety_check(self, text: str, owner_id: str, claim_id: str) -> bool:
        if not self.settings.enable_nvidia_safety or not self.settings.nvidia_safety_model:
            return True
        try:
            result = await self.structured(TaskType.SAFETY, [
                {"role": "system", "content": "Classify requests for healthcare administrative assistance. "
                 "Flag requests for diagnosis, treatment, fraud, or autonomous claim decisions."},
                {"role": "user", "content": text},
            ], SafetyResult, owner_id, claim_id)
            return not result.value.unsafe
        except Exception:
            # Optional endpoint cannot take down the application; deterministic controls remain active.
            return True

    def configuration_fingerprint(self) -> str:
        return cache_key([self.router.select_model(task).model_dump() for task in TaskType],
                         self.settings.nvidia_embedding_dimension,
                         json.dumps({"context": self.settings.max_context_tokens,
                                     "rerank": self.settings.enable_reranking}))
