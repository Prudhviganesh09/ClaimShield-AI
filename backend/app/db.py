import ssl
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import Settings


def now():
    return datetime.now(UTC)


def new_id():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "cs_users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Claim(Base):
    __tablename__ = "cs_claims"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("cs_users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    claim_number: Mapped[str] = mapped_column(String(100), default="")
    insurer: Mapped[str] = mapped_column(String(200), default="")
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="collecting_evidence")
    review_notes: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Document(Base):
    __tablename__ = "cs_documents"
    __table_args__ = (UniqueConstraint("claim_id", "checksum", name="uq_document_checksum"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    claim_id: Mapped[str] = mapped_column(ForeignKey("cs_claims.id"), index=True)
    name: Mapped[str] = mapped_column(String(250))
    checksum: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="uploaded")
    document_type: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    extraction_method: Mapped[str] = mapped_column(String(40), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0)
    fields: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    extracted_pages: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Chunk(Base):
    __tablename__ = "cs_chunks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("cs_documents.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("cs_claims.id"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    # Variable dimensions: metadata filters prevent comparisons across incompatible models.
    embedding: Mapped[list | None] = mapped_column(Vector().with_variant(JSON(), "sqlite"), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Analysis(Base):
    __tablename__ = "cs_analyses"
    __table_args__ = (UniqueConstraint("claim_id", "cache_key", name="uq_analysis_cache"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    claim_id: Mapped[str] = mapped_column(ForeignKey("cs_claims.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    question: Mapped[str] = mapped_column(Text)
    cache_key: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(200))
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AIUsage(Base):
    __tablename__ = "cs_ai_usage"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(200))
    task: Mapped[str] = mapped_column(String(50))
    request_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    latency_ms: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean)
    retry_count: Mapped[int] = mapped_column(Integer)
    fallback_used: Mapped[bool] = mapped_column(Boolean)
    claim_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_id: Mapped[str] = mapped_column(String(36), index=True)


class Database:
    def __init__(self, settings: Settings):
        if settings.database_url.startswith("sqlite"):
            self.engine = create_async_engine(settings.database_url, hide_parameters=True)
        else:
            # Persistent backend uses Supabase direct/session mode (5432), not transaction mode (6543).
            from sqlalchemy.engine import make_url
            url = make_url(settings.database_url)
            if url.port == 6543:
                raise ValueError("Use Supabase direct or session-pooler connection on port 5432")
            ssl_context = False
            if settings.database_ssl:
                ssl_context = ssl.create_default_context()
                ca_file = settings.database_ssl_ca_file
                if ca_file is None and url.host and url.host.endswith((".supabase.co", ".pooler.supabase.com")):
                    ca_file = Path(__file__).resolve().parents[1] / "certs/prod-supabase.cer"
                if ca_file:
                    ssl_context.load_verify_locations(str(ca_file))
            # asyncpg takes a verified SSLContext rather than libpq's sslmode URL parameter.
            if "sslmode" in url.query:
                if url.query["sslmode"] not in ("require", "verify-ca", "verify-full") or not settings.database_ssl:
                    raise ValueError("Use DATABASE_SSL=true with a verified TLS database connection")
                url = url.difference_update_query(["sslmode"])
            self.engine = create_async_engine(url, pool_size=settings.database_pool_size,
                max_overflow=0, pool_pre_ping=True, pool_recycle=300, hide_parameters=True,
                connect_args={"ssl": ssl_context,
                              "server_settings": {"search_path": "public,extensions"}})
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def initialize_for_tests(self):
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def record_usage(self, values: dict):
        async with self.sessions() as session:
            session.add(AIUsage(**values))
            await session.commit()

    async def ping(self):
        async with self.sessions() as session:
            await session.execute(text("SELECT 1"))
