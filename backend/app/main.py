import asyncio
import logging
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.ai.cache import cache_key
from app.ai.client import AIClient
from app.ai.embeddings import NvidiaEmbeddingService
from app.ai.providers.base import AIError
from app.ai.providers.nvidia import NvidiaProvider
from app.auth import (
    DUMMY_HASH,
    admin_user,
    current_user,
    hash_password,
    public_user,
    set_session,
    verify_password,
)
from app.config import Settings, get_settings
from app.db import AIUsage, Analysis, Claim, Database, Document, User, new_id
from app.schemas import ClaimCreate, Credentials, Question, Register, Review
from app.services.analysis import AnalysisService
from app.services.documents import DocumentService, checksum
from app.services.retrieval import RetrievalService

logger = logging.getLogger(__name__)


def serialize(row, excluded=()):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns
            if column.name not in excluded}


def public_document(doc):
    return serialize(doc, ("storage_path", "extracted_pages", "checksum"))


class RateLimiter:
    def __init__(self):
        self.entries = OrderedDict()

    def check(self, key: str, limit: int, seconds: int = 60):
        now = time.monotonic()
        times = [t for t in self.entries.pop(key, []) if now-t < seconds]
        if len(times) >= limit:
            self.entries[key] = times
            raise HTTPException(429, "Too many requests. Please wait a minute and try again")
        times.append(now)
        self.entries[key] = times
        while len(self.entries) > 2000:
            self.entries.popitem(last=False)


async def get_claim(request: Request, claim_id: str, user: User) -> Claim:
    async with request.app.state.db.sessions() as session:
        claim = await session.get(Claim, claim_id)
    if not claim or (claim.owner_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Claim not found")
    return claim


def create_app(settings: Settings | None = None, database: Database | None = None,
               provider: NvidiaProvider | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = database or Database(settings)
    provider = provider or NvidiaProvider(settings, db.record_usage)
    ai = AIClient(provider, settings)
    embeddings = NvidiaEmbeddingService(ai)
    retrieval = RetrievalService(db, embeddings)
    documents = DocumentService(db, ai, embeddings)
    analyses = AnalysisService(db, ai, retrieval)
    limiter = RateLimiter()

    @asynccontextmanager
    async def lifespan(app):
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        await db.ping()
        async with db.sessions() as session:
            # Interrupted processing is visible and retryable after a process restart.
            await session.execute(update(Document).where(Document.status == "processing").values(
                status="needs_retry", error="Processing was interrupted. Retry indexing; the original is saved."))
            if settings.admin_email:
                existing = await session.scalar(select(User).where(User.email == settings.admin_email.lower()))
                if not existing:
                    session.add(User(email=settings.admin_email.lower(), name="Administrator", role="admin",
                                     password_hash=await hash_password(settings.admin_password.get_secret_value())))
            await session.commit()
        async with db.sessions() as session:
            queued = (await session.execute(select(Document.id, Claim.owner_id).join(
                Claim, Document.claim_id == Claim.id).where(Document.status == "uploaded"))).all()
        for document_id, owner_id in queued:
            documents.start(document_id, owner_id)
        try:
            yield
        finally:
            if documents.jobs:
                try:
                    await asyncio.wait_for(asyncio.gather(*list(documents.jobs.values()),
                                                          return_exceptions=True), timeout=30)
                except TimeoutError:
                    pass  # Interrupted document jobs become retryable on the next startup.
            await analyses.requests.close()
            await retrieval.cache.close()
            await embeddings.cache.close()
            await ai.responses.close()
            await provider.close()
            await db.engine.dispose()

    app = FastAPI(title="ClaimShield AI", version="1.0.0", lifespan=lifespan)
    app.state.settings, app.state.db, app.state.ai = settings, db, ai
    app.state.documents, app.state.analyses = documents, analyses
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins,
                       allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.middleware("http")
    async def protect_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin not in settings.allowed_origins:
            return JSONResponse({"detail": "Request origin is not allowed"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(AIError)
    async def handle_ai_error(request, exc):
        status = 422 if exc.code in ("out_of_scope", "missing_evidence") else 503
        return JSONResponse({"detail": exc.message, "code": exc.code, "data_preserved": True}, status_code=status)

    @app.exception_handler(Exception)
    async def handle_internal_error(request, exc):
        logger.error("Request failed: %s", type(exc).__name__)
        return JSONResponse({"detail": "The request could not be completed. Please retry."}, status_code=500)

    @app.get("/api/health")
    async def health():
        try:
            await db.ping()
        except Exception:
            return JSONResponse({"status": "unavailable", "database": False}, status_code=503)
        return {"status": "ok", "database": True, "ai_provider": "nvidia"}

    @app.post("/api/auth/register", status_code=201)
    async def register(body: Register, request: Request, response: Response):
        limiter.check(cache_key("register", request.client.host), 5)
        async with db.sessions() as session:
            user = User(email=body.email, name=body.name.strip(), password_hash=await hash_password(body.password))
            session.add(user)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise HTTPException(409, "An account with this email already exists") from exc
        set_session(response, user, settings)
        return public_user(user)

    @app.post("/api/auth/login")
    async def login(body: Credentials, request: Request, response: Response):
        limiter.check(cache_key("login", request.client.host, body.email), 10)
        async with db.sessions() as session:
            user = await session.scalar(select(User).where(User.email == body.email))
        valid = await verify_password(body.password, user.password_hash if user else DUMMY_HASH)
        if not valid or not user:
            raise HTTPException(401, "Email or password is incorrect")
        set_session(response, user, settings)
        return public_user(user)

    @app.post("/api/auth/logout")
    async def logout(response: Response):
        response.delete_cookie("claimshield_session", path="/", secure=settings.cookie_secure,
                               httponly=True, samesite="strict")
        return {"success": True}

    @app.get("/api/auth/me")
    async def me(user: User = Depends(current_user)):
        return public_user(user)

    @app.get("/api/config")
    async def config(user: User = Depends(current_user)):
        return {"demo_mode": settings.demo_mode, "max_upload_mb": settings.max_upload_mb,
                "max_document_pages": settings.max_document_pages, "provider": "nvidia"}

    @app.get("/api/claims")
    async def list_claims(user: User = Depends(current_user), offset: int = 0):
        if offset < 0:
            raise HTTPException(422, "Offset must be nonnegative")
        async with db.sessions() as session:
            query = select(Claim).order_by(Claim.updated_at.desc()).offset(offset).limit(100)
            if user.role != "admin":
                query = query.where(Claim.owner_id == user.id)
            return [serialize(c) for c in (await session.scalars(query)).all()]

    @app.post("/api/claims", status_code=201)
    async def create_claim(body: ClaimCreate, user: User = Depends(current_user)):
        async with db.sessions() as session:
            claim = Claim(owner_id=user.id, **body.model_dump())
            session.add(claim)
            await session.commit()
        return serialize(claim)

    @app.get("/api/claims/{claim_id}")
    async def claim_detail(claim_id: str, request: Request, user: User = Depends(current_user)):
        claim = await get_claim(request, claim_id, user)
        async with db.sessions() as session:
            docs = (await session.scalars(select(Document).where(Document.claim_id == claim.id).order_by(
                Document.created_at))).all()
            history = (await session.scalars(select(Analysis).where(Analysis.claim_id == claim.id).order_by(
                Analysis.created_at.desc()).limit(30))).all()
        return {**serialize(claim), "documents": [public_document(d) for d in docs],
                "analyses": [serialize(a, ("cache_key",)) for a in history]}

    @app.post("/api/claims/{claim_id}/review")
    async def review(claim_id: str, body: Review, request: Request, user: User = Depends(current_user)):
        claim = await get_claim(request, claim_id, user)
        async with db.sessions() as session:
            await session.execute(update(Claim).where(Claim.id == claim.id).values(
                status=body.status, review_notes=body.notes))
            await session.commit()
        return {"status": body.status, "review_notes": body.notes}

    @app.post("/api/claims/{claim_id}/documents", status_code=201)
    async def upload_document(claim_id: str, request: Request, file: UploadFile = File(...),
                              user: User = Depends(current_user)):
        claim = await get_claim(request, claim_id, user)
        limiter.check(cache_key("upload", user.id), 20)
        supported = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
                     ".jpeg": "image/jpeg", ".txt": "text/plain"}
        name = (file.filename or "document").replace("\\", "/").split("/")[-1][:250]
        suffix = Path(name).suffix.lower()
        if suffix not in supported:
            raise HTTPException(422, "Upload a PDF, PNG, JPEG, or UTF-8 text file")
        content = bytearray()
        try:
            while block := await file.read(64*1024):
                content.extend(block)
                if len(content) > settings.max_upload_mb*1024*1024:
                    raise HTTPException(413, f"Maximum upload size is {settings.max_upload_mb} MB")
        finally:
            await file.close()
        if not content:
            raise HTTPException(422, "The uploaded file is empty")
        if suffix == ".pdf" and not content.startswith(b"%PDF-"):
            raise HTTPException(422, "This file is not a valid PDF")
        if suffix in (".jpg", ".jpeg") and not content.startswith(b"\xff\xd8\xff"):
            raise HTTPException(422, "This file is not a valid JPEG")
        if suffix == ".png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(422, "This file is not a valid PNG")
        digest = checksum(content)
        async with db.sessions() as session:
            existing = await session.scalar(select(Document).where(Document.claim_id == claim.id,
                                                                   Document.checksum == digest))
            if existing:
                return {**public_document(existing), "duplicate": True}
            count = await session.scalar(select(func.count()).select_from(Document).where(Document.claim_id == claim.id))
            if count >= 50:
                raise HTTPException(422, "A claim can contain up to 50 documents")
        doc_id = new_id()
        path = settings.upload_dir.resolve() / (doc_id+suffix)
        await asyncio.to_thread(path.write_bytes, content)
        doc = Document(id=doc_id, claim_id=claim.id, name=name, checksum=digest,
                       storage_path=str(path), media_type=supported[suffix])
        async with db.sessions() as session:
            if db.engine.dialect.name == "postgresql":
                # Serialize the per-claim capacity check on Supabase, including concurrent uploads.
                await session.execute(select(Claim.id).where(Claim.id == claim.id).with_for_update())
                count = await session.scalar(select(func.count()).select_from(Document).where(
                    Document.claim_id == claim.id))
                if count >= 50:
                    await asyncio.to_thread(path.unlink, missing_ok=True)
                    raise HTTPException(422, "A claim can contain up to 50 documents")
            session.add(doc)
            try:
                await session.execute(update(Claim).where(Claim.id == claim.id).values(revision=Claim.revision+1))
                await session.commit()
            except IntegrityError:
                await session.rollback()
                await asyncio.to_thread(path.unlink, missing_ok=True)
                existing = await session.scalar(select(Document).where(Document.claim_id == claim.id,
                                                                       Document.checksum == digest))
                if existing:
                    return {**public_document(existing), "duplicate": True}
                raise
        # Original upload is committed before any NVIDIA call. Extraction/indexing is explicitly retryable.
        documents.start(doc_id, claim.owner_id)
        return public_document(doc)

    async def authorize_document(document_id, request, user):
        async with db.sessions() as session:
            doc = await session.get(Document, document_id)
        if not doc:
            raise HTTPException(404, "Document not found")
        claim = await get_claim(request, doc.claim_id, user)
        return doc, claim

    @app.get("/api/documents/{document_id}/download")
    async def download(document_id: str, request: Request, user: User = Depends(current_user)):
        doc, _ = await authorize_document(document_id, request, user)
        if not Path(doc.storage_path).is_file():
            raise HTTPException(404, "Original file is unavailable. Restore the uploads volume from backup")
        return FileResponse(doc.storage_path, filename=doc.name, media_type=doc.media_type,
                            content_disposition_type="attachment")

    @app.get("/api/analyses/{analysis_id}/appeal/download")
    async def download_appeal(analysis_id: str, request: Request, user: User = Depends(current_user)):
        async with db.sessions() as session:
            analysis = await session.get(Analysis, analysis_id)
        if not analysis:
            raise HTTPException(404, "Analysis not found")
        await get_claim(request, analysis.claim_id, user)
        paragraphs = analysis.result.get("appeal_paragraphs", [])
        if analysis.kind != "appeal" or not paragraphs:
            raise HTTPException(422, "This report has no appeal paragraphs to export")
        sources = {source["chunk_id"]: source for source in analysis.result["sources"]}
        lines = ["DRAFT — HUMAN REVIEW REQUIRED", ""]
        for paragraph in paragraphs:
            lines.append(paragraph["statement"])
            for citation in paragraph["citations"]:
                source = sources[citation["chunk_id"]]
                lines.append(f"Source: {source['document_name']}, page {source['page']}: {citation['quote']}")
            lines.append("")
        return Response("\n".join(lines), media_type="text/plain; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="claimshield-appeal-draft.txt"'})

    @app.post("/api/documents/{document_id}/retry")
    async def retry_document(document_id: str, request: Request, user: User = Depends(current_user)):
        doc, claim = await authorize_document(document_id, request, user)
        limiter.check(cache_key("retry", user.id), 10)
        async with db.sessions() as session:
            await session.execute(update(Document).where(Document.id == doc.id).values(status="processing", error=None))
            await session.commit()
        documents.start(doc.id, claim.owner_id)
        return {"id": doc.id, "status": "processing"}

    async def run_analysis(claim_id, request, user, question, kind):
        claim = await get_claim(request, claim_id, user)
        limiter.check(cache_key("analysis", user.id), 10)
        result = await analyses.analyze(claim, claim.owner_id, question, kind)
        return serialize(result, ("cache_key",))

    @app.post("/api/claims/{claim_id}/analyze")
    async def analyze(claim_id: str, request: Request, user: User = Depends(current_user)):
        return await run_analysis(claim_id, request, user,
            "Analyze the claim denial, compare it against the applicable policy, identify contradictions and "
            "missing information, and recommend administrative next steps grounded in the supplied documents.", "analysis")

    @app.post("/api/claims/{claim_id}/appeal")
    async def appeal(claim_id: str, request: Request, user: User = Depends(current_user)):
        return await run_analysis(claim_id, request, user,
            "Draft an administrative appeal for human review using only the supplied evidence. Identify missing "
            "information and support each appeal paragraph with exact cited quotes. Do not invent deadlines.", "appeal")

    @app.post("/api/claims/{claim_id}/chat")
    async def chat(claim_id: str, body: Question, request: Request, user: User = Depends(current_user)):
        return await run_analysis(claim_id, request, user, body.question, "chat")

    @app.get("/api/admin/providers/nvidia/health")
    async def provider_health(user: User = Depends(admin_user)):
        return await provider.health_check()

    @app.get("/api/admin/usage")
    async def usage(user: User = Depends(admin_user)):
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        month = today.replace(day=1)
        async with db.sessions() as session:
            totals = (await session.execute(select(func.count(), func.coalesce(func.sum(
                AIUsage.input_tokens+AIUsage.output_tokens), 0), func.coalesce(func.avg(AIUsage.latency_ms), 0),
                func.count().filter(AIUsage.http_status == 429), func.count().filter(AIUsage.success.is_(False)),
                func.count().filter(AIUsage.request_timestamp >= today),
                func.count().filter(AIUsage.request_timestamp >= month)).select_from(AIUsage))).one()
            distribution = (await session.execute(select(AIUsage.model, func.count()).group_by(AIUsage.model))).all()
        return {"provider": "nvidia", "mode": settings.ai_usage_mode, "requests": totals[0],
                "token_estimate": totals[1], "average_latency_ms": round(totals[2]),
                "rate_limit_events": totals[3], "failed_requests": totals[4],
                "requests_today": totals[5], "requests_this_month": totals[6],
                "model_distribution": [{"model": model, "requests": count} for model, count in distribution],
                "timezone": "UTC", "cost": None,
                "cost_note": "Dollar cost is unavailable without verified model pricing. Request counts include retries."}

    @app.post("/api/demo", status_code=201)
    async def demo(request: Request, user: User = Depends(current_user)):
        if not settings.demo_mode:
            raise HTTPException(404, "Demo mode is disabled")
        limiter.check(cache_key("demo", user.id), 2, 3600)
        examples = {
            "sample-denial.txt": "SYNTHETIC DEMO DOCUMENT\nInsurer: Example Health\nClaim ID: DEMO-1042\n"
                "Denial code: AUTH-01\nDenial reason: Prior authorization record was not provided.\n"
                "The claim was denied pending documentation of authorization. This is fictional sample data.",
            "sample-policy.txt": "SYNTHETIC DEMO DOCUMENT\nCoverage policy: Example Plan\nPolicy provisions:\n"
                "Administrative review requires an itemized bill and a copy of the prior authorization record.\n"
                "Members may request reconsideration with supporting documents. No appeal deadline is specified "
                "in this fictional excerpt.",
            "sample-bill.txt": "SYNTHETIC DEMO DOCUMENT\nItemized bill\nClaim ID: DEMO-1042\n"
                "Insurer: Example Health\nAmount due: 245.00\nAdministrative service line: 245.00\n"
                "No authorization reference appears on this fictional sample bill.",
        }
        document_ids = []
        async with db.sessions() as session:
            claim = Claim(owner_id=user.id, title="Sample authorization denial", claim_number="DEMO-1042",
                          insurer="Example Health", amount=245, revision=1)
            session.add(claim)
            await session.flush()
            for name, content in examples.items():
                doc_id = new_id()
                document_ids.append(doc_id)
                path = settings.upload_dir.resolve() / (doc_id+".txt")
                await asyncio.to_thread(path.write_text, content, encoding="utf-8")
                session.add(Document(id=doc_id, claim_id=claim.id, name=name, checksum=checksum(content.encode()),
                                     storage_path=str(path), media_type="text/plain"))
            await session.commit()
        for document_id in document_ids:
            documents.start(document_id, user.id)
        return serialize(claim)

    return app


app = create_app()
