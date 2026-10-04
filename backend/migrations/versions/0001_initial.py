"""ClaimShield schema, isolated from Supabase's auth and storage schemas."""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("cs_users", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("cs_claims", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("cs_users.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False), sa.Column("claim_number", sa.String(100), nullable=False),
        sa.Column("insurer", sa.String(200), nullable=False), sa.Column("amount", sa.Float()),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("review_notes", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_cs_claims_owner_id", "cs_claims", ["owner_id"])
    op.create_table("cs_documents", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("claim_id", sa.String(36), sa.ForeignKey("cs_claims.id"), nullable=False),
        sa.Column("name", sa.String(250), nullable=False), sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False), sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("document_type", sa.String(30), nullable=False),
        sa.Column("extraction_method", sa.String(40), nullable=False), sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False), sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("extracted_pages", sa.JSON(), nullable=False), sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("claim_id", "checksum", name="uq_document_checksum"))
    op.create_index("ix_cs_documents_claim_id", "cs_documents", ["claim_id"])
    op.create_table("cs_chunks", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("cs_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("claim_id", sa.String(36), sa.ForeignKey("cs_claims.id"), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False), sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector()), sa.Column("embedding_model", sa.String(200)),
        sa.Column("embedding_dimension", sa.Integer()),
        sa.Column("embedding_created_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_cs_chunks_document_id", "cs_chunks", ["document_id"])
    op.create_index("ix_cs_chunks_claim_id", "cs_chunks", ["claim_id"])
    op.execute("CREATE INDEX ix_cs_chunks_search ON cs_chunks USING gin (to_tsvector('english', text))")
    op.create_table("cs_analyses", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("claim_id", sa.String(36), sa.ForeignKey("cs_claims.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False), sa.Column("question", sa.Text(), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False), sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(200), nullable=False), sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("claim_id", "cache_key", name="uq_analysis_cache"))
    op.create_index("ix_cs_analyses_claim_id", "cs_analyses", ["claim_id"])
    op.create_table("cs_ai_usage", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False), sa.Column("model", sa.String(200), nullable=False),
        sa.Column("task", sa.String(50), nullable=False),
        sa.Column("request_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False), sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False), sa.Column("http_status", sa.Integer()),
        sa.Column("success", sa.Boolean(), nullable=False), sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False), sa.Column("claim_id", sa.String(36)),
        sa.Column("owner_id", sa.String(36)), sa.Column("request_id", sa.String(36), nullable=False))
    op.create_index("ix_cs_ai_usage_request_timestamp", "cs_ai_usage", ["request_timestamp"])
    op.create_index("ix_cs_ai_usage_request_id", "cs_ai_usage", ["request_id"])
    # Prevent anonymous/authenticated Supabase REST access. Backend connects with its database role.
    for table in ("cs_users", "cs_claims", "cs_documents", "cs_chunks", "cs_analyses", "cs_ai_usage"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON {table} FROM anon, authenticated")


def downgrade():
    for table in ("cs_ai_usage", "cs_analyses", "cs_chunks", "cs_documents", "cs_claims", "cs_users"):
        op.drop_table(table)
