import importlib.util
import ssl
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import postgresql

from app.config import Settings
from app.db import Chunk, Database, Document


def test_supabase_migration_compiles_with_pgvector_and_rls():
    statements = []
    def collect(statement, *multiparams, **params):
        statements.append(str(statement.compile(dialect=postgresql.dialect())))
    engine = sa.create_mock_engine("postgresql://", collect)
    context = MigrationContext.configure(engine.connect())
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0001_initial.py"
    spec = importlib.util.spec_from_file_location("initial", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Operations.context(context):
        migration.upgrade()
    sql = "\n".join(statements)
    assert "embedding VECTOR" in sql
    assert "USING gin" in sql
    assert sql.count("ENABLE ROW LEVEL SECURITY") == 6
    assert sql.count("FROM anon, authenticated") == 6
    assert "uq_document_checksum" in sql and "uq_analysis_cache" in sql


def test_hybrid_retrieval_compiles_model_dimension_filters_and_full_text():
    vector = [1, 0.5, 0.3]
    distance = Chunk.embedding.cosine_distance(vector)
    query = sa.select(Chunk, Document, distance).join(Document, Chunk.document_id == Document.id).where(
        Chunk.claim_id == "claim", Document.status == "ready", Chunk.embedding_model == "model",
        Chunk.embedding_dimension == len(vector)).order_by(distance).limit(24)
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "<=>" in sql and "embedding_model" in sql and "embedding_dimension" in sql
    query = sa.select(Chunk).where(sa.func.to_tsvector("english", Chunk.text).op("@@")(
        sa.func.plainto_tsquery("english", "denial authorization")))
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "to_tsvector" in sql and "plainto_tsquery" in sql and "@@" in sql


async def test_supabase_tls_trusts_vendor_ca_and_verifies_hostname(monkeypatch):
    import app.db as database_module
    original = database_module.create_async_engine
    captured = {}
    def capture(url, **kwargs):
        captured.update(url=url, **kwargs)
        return original(url, **kwargs)
    monkeypatch.setattr(database_module, "create_async_engine", capture)
    db = Database(Settings(_env_file=None, app_env="test",
        database_url="postgresql+asyncpg://postgres.test:example@aws-0-ap-south-1.pooler.supabase.com:5432/postgres?sslmode=require"))
    context = captured["connect_args"]["ssl"]
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert "sslmode" not in captured["url"].query
    assert any(("commonName", "Supabase Root 2021 CA") in group
               for cert in context.get_ca_certs() for group in cert["subject"])
    await db.engine.dispose()


def test_transaction_pooler_is_rejected():
    with pytest.raises(ValueError, match="session-pooler"):
        Database(Settings(_env_file=None, app_env="test",
            database_url="postgresql+asyncpg://postgres.test:example@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"))
