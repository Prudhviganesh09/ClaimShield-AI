from app.ai.cache import AsyncCache, cache_key
from app.ai.client import AIClient
from app.ai.router.model_router import TaskType


class NvidiaEmbeddingService:
    def __init__(self, client: AIClient):
        self.client = client
        self.cache = AsyncCache(64, ttl=3600)

    async def _embed(self, texts: list[str], mode: str, owner_id: str, claim_id: str):
        config = self.client.router.select_model(TaskType.EMBEDDING)
        key = cache_key(owner_id, mode, config.model, self.client.settings.nvidia_embedding_dimension, texts)
        return await self.cache.get_or_create(key, lambda: self.client.provider.embed(
            texts, mode, config, self.client.context(TaskType.EMBEDDING, owner_id, claim_id)))

    async def passage_embeddings(self, texts: list[str], owner_id: str, claim_id: str) -> list[list[float]]:
        batch = self.client.settings.nvidia_embedding_batch_size
        vectors = []
        for offset in range(0, len(texts), batch):
            result = await self._embed(texts[offset:offset+batch], "passage", owner_id, claim_id)
            vectors.extend(result.vectors)
        return vectors

    async def query_embedding(self, text: str, owner_id: str, claim_id: str) -> list[float]:
        return (await self._embed([text], "query", owner_id, claim_id)).vectors[0]
