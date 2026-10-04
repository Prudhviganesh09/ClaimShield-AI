import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy import func, select

from app.ai.cache import AsyncCache, cache_key
from app.ai.embeddings import NvidiaEmbeddingService
from app.db import Chunk, Database, Document


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


@dataclass
class Evidence:
    chunk_id: str
    document_id: str
    document_name: str
    document_type: str
    page: int
    text: str
    confidence: float
    vector_score: float = 0
    text_score: float = 0
    score: float = 0


class BaseReranker(ABC):
    @abstractmethod
    def rerank(self, question: str, candidates: list[Evidence]) -> list[Evidence]: ...


class HeuristicReranker(BaseReranker):
    def rerank(self, question: str, candidates: list[Evidence]) -> list[Evidence]:
        tokens = words(question)
        for candidate in candidates:
            overlap = len(tokens & words(candidate.text)) / max(1, len(tokens))
            priority = 1 if candidate.document_type in ("POLICY", "DENIAL_LETTER") else 0.5
            candidate.score = (0.50*candidate.vector_score + 0.20*candidate.text_score +
                               0.25*overlap + 0.05*priority)
        return sorted(candidates, key=lambda c: c.score, reverse=True)


class RetrievalService:
    def __init__(self, db: Database, embeddings: NvidiaEmbeddingService):
        self.db, self.embeddings = db, embeddings
        self.reranker = HeuristicReranker()
        self.cache = AsyncCache(64, 300)

    async def retrieve(self, claim_id: str, owner_id: str, question: str, revision: int) -> list[Evidence]:
        s = self.embeddings.client.settings
        key = cache_key(owner_id, claim_id, question, revision, s.nvidia_embedding_model,
                        s.nvidia_embedding_dimension, s.max_context_tokens, s.enable_reranking)
        return await self.cache.get_or_create(key, lambda: self._retrieve(claim_id, owner_id, question))

    async def _retrieve(self, claim_id: str, owner_id: str, question: str):
        vector = await self.embeddings.query_embedding(question, owner_id, claim_id)
        settings = self.embeddings.client.settings
        async with self.db.sessions() as session:
            base = select(Chunk, Document).join(Document, Chunk.document_id == Document.id).where(
                Chunk.claim_id == claim_id, Document.status == "ready",
                Chunk.embedding_model == settings.nvidia_embedding_model,
                Chunk.embedding_dimension == len(vector))
            if self.db.engine.dialect.name == "postgresql":
                distance = Chunk.embedding.cosine_distance(vector)
                semantic_rows = (await session.execute(base.add_columns(distance).order_by(distance).limit(24))).all()
                query = func.plainto_tsquery("english", question)
                rank = func.ts_rank_cd(func.to_tsvector("english", Chunk.text), query)
                lexical_rows = (await session.execute(base.add_columns(rank).where(
                    func.to_tsvector("english", Chunk.text).op("@@")(query)).order_by(rank.desc()).limit(24))).all()
            else:
                # SQLite exists only in the test suite; deployment uses pgvector and PostgreSQL full text.
                rows = (await session.execute(base)).all()
                def cosine(v):
                    return sum(a*b for a, b in zip(v, vector, strict=True)) / max(1e-12,
                        math.sqrt(sum(a*a for a in v)*sum(b*b for b in vector)))
                semantic_rows = [(c, d, 1-cosine(c.embedding)) for c, d in rows]
                semantic_rows.sort(key=lambda row: row[2])
                semantic_rows = semantic_rows[:24]
                lexical_rows = [(c, d, len(words(question) & words(c.text))/max(1, len(words(question))))
                                for c, d in rows]
                lexical_rows = sorted(lexical_rows, key=lambda row: row[2], reverse=True)[:24]
        candidates = {}
        for chunk, doc, distance in semantic_rows:
            candidates[chunk.id] = Evidence(chunk.id, doc.id, doc.name, doc.document_type, chunk.page,
                                            chunk.text, doc.confidence,
                                            vector_score=max(0, min(1, 1-float(distance))))
        maximum = max([float(row[2]) for row in lexical_rows], default=1) or 1
        for chunk, doc, rank in lexical_rows:
            if chunk.id not in candidates:
                candidates[chunk.id] = Evidence(chunk.id, doc.id, doc.name, doc.document_type, chunk.page,
                                                chunk.text, doc.confidence)
            candidates[chunk.id].text_score = float(rank)/maximum
        ranked = self.reranker.rerank(question, list(candidates.values())) if settings.enable_reranking else (
            sorted(candidates.values(), key=lambda c: c.vector_score+c.text_score, reverse=True))
        budget, selected, seen = settings.max_context_tokens, [], set()
        for candidate in ranked:
            signature = re.sub(r"\s+", " ", candidate.text).strip()
            if signature in seen:
                continue
            cost = self.embeddings.client.provider.estimate_tokens(candidate.text) + 100
            if cost > budget:
                continue
            seen.add(signature)
            budget -= cost
            selected.append(candidate)
            if len(selected) == 10:
                break
        return selected
