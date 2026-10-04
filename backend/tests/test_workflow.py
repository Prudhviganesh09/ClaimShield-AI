import asyncio
import json
from contextlib import asynccontextmanager

import fitz
import httpx
import pytest
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import select

from app.ai.providers.nvidia import NvidiaProvider
from app.config import Settings
from app.db import AIUsage, Analysis, Chunk, Database, User
from app.main import create_app
from app.schemas import VisionDocumentExtraction
from app.services.documents import chunk_text, extract_local, local_metadata, ocr_page


@pytest.fixture
async def app(tmp_path):
    s = Settings(_env_file=None, app_env="test", database_url="sqlite+aiosqlite:///"+str(tmp_path/"db.sqlite"),
                 upload_dir=tmp_path/"uploads", nvidia_api_key="test-key", nvidia_embedding_dimension=3,
                 nvidia_max_retries=0, cookie_secure=False)
    db = Database(s)
    await db.initialize_for_tests()
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if request.url.path.endswith("embeddings"):
            return httpx.Response(200, json={"data": [{"index": i, "embedding": [1.0, 0.5, 0.3]}
                                                       for i in range(len(body["input"]))]})
        text = body["messages"][-1]["content"]
        if "unsupported_indexes" in body["messages"][0]["content"]:
            value = {"supported": True, "unsupported_indexes": []}
        else:
            prompt = json.loads(text)
            source = prompt["evidence"][0]
            value = {"findings": [{"statement": "The supplied document records an administrative claim issue.",
                "kind": "fact", "citations": [{"chunk_id": source["chunk_id"], "quote": source["text"][:50]}]}],
                "recommendations": [], "appeal_paragraphs": [], "missing_information": [],
                "insufficient_evidence": False}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}, "finish_reason": "stop"}]})
    provider = NvidiaProvider(s, db.record_usage, httpx.MockTransport(handler))
    app = create_app(s, db, provider)
    app.state.test_calls = calls
    async with app.router.lifespan_context(app):
        yield app


@asynccontextmanager
async def client(app, email="first@example.com"):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        result = await c.post("/api/auth/register", json={"email": email, "name": "Reviewer", "password": "correct-password-123"})
        assert result.status_code == 201
        assert "HttpOnly" in result.headers["set-cookie"]
        yield c


async def finish_jobs(app):
    while app.state.documents.jobs:
        await asyncio.gather(*list(app.state.documents.jobs.values()))


async def make_claim(c):
    result = await c.post("/api/claims", json={"title": "Claim review", "claim_number": "ABC-123"})
    assert result.status_code == 201
    return result.json()["id"]


TEXT = "Claim ID: ABC-123\nInsurer: Example Health\nDenial reason: The claim was denied because authorization was missing."


async def upload(c, claim_id, text=TEXT):
    result = await c.post(f"/api/claims/{claim_id}/documents", files={"file": ("denial.txt", text, "text/plain")})
    assert result.status_code == 201
    return result.json()


async def test_full_workflow_upload_index_retrieve_analyze_cache_review(app):
    async with client(app) as c:
        claim_id = await make_claim(c)
        doc = await upload(c, claim_id)
        await finish_jobs(app)
        detail = (await c.get(f"/api/claims/{claim_id}")).json()
        assert detail["documents"][0]["status"] == "ready"
        assert detail["documents"][0]["extraction_method"] == "text"
        assert detail["documents"][0]["fields"]["claim_id"] == "ABC-123"
        async with app.state.db.sessions() as session:
            assert (await session.scalar(select(Chunk))).embedding_created_at is not None
        assert "storage_path" not in detail["documents"][0]
        original = await c.get(f"/api/documents/{doc['id']}/download")
        assert original.content.decode() == TEXT
        report = await c.post(f"/api/claims/{claim_id}/analyze")
        assert report.status_code == 200, report.text
        assert report.json()["result"]["findings"][0]["citations"]
        assert report.json()["result"]["requires_human_review"]
        count = len(app.state.test_calls)
        cached = await c.post(f"/api/claims/{claim_id}/analyze")
        assert cached.json()["id"] == report.json()["id"]
        assert len(app.state.test_calls) == count
        duplicate = await upload(c, claim_id)
        assert duplicate["duplicate"] and duplicate["id"] == doc["id"]
        assert len(app.state.test_calls) == count
        review = await c.post(f"/api/claims/{claim_id}/review", json={"status": "reviewed", "notes": "Verified original."})
        assert review.status_code == 200
        assert (await c.get(f"/api/claims/{claim_id}")).json()["review_notes"] == "Verified original."


async def test_tenant_isolation_and_admin_boundary(app):
    async with client(app) as first, client(app, "second@example.com") as second:
        claim_id = await make_claim(first)
        doc = await upload(first, claim_id)
        await finish_jobs(app)
        for path in [f"/api/claims/{claim_id}", f"/api/documents/{doc['id']}/download"]:
            assert (await second.get(path)).status_code == 404
        assert (await second.post(f"/api/claims/{claim_id}/analyze")).status_code == 404
        assert (await second.post(f"/api/documents/{doc['id']}/retry")).status_code == 404
        assert (await second.get("/api/claims")).json() == []
        assert (await first.get("/api/admin/usage")).status_code == 403
        assert (await first.get("/api/admin/providers/nvidia/health")).status_code == 403


async def test_outage_preserves_uploads_login_claims_and_prior_results(app):
    async with client(app) as c:
        claim_id = await make_claim(c)
        await upload(c, claim_id)
        await finish_jobs(app)
        assert (await c.post(f"/api/claims/{claim_id}/analyze")).status_code == 200
        app.state.ai.provider.settings.nvidia_api_key = app.state.ai.provider.settings.nvidia_api_key.__class__("")
        doc = await upload(c, claim_id, TEXT + " Additional unsupported record for retry.")
        await finish_jobs(app)
        detail = (await c.get(f"/api/claims/{claim_id}")).json()
        failed = next(d for d in detail["documents"] if d["id"] == doc["id"])
        assert failed["status"] == "needs_retry" and "API key" in failed["error"]
        assert len(detail["analyses"]) == 1
        assert (await c.get(f"/api/documents/{doc['id']}/download")).status_code == 200
        assert (await c.get("/api/claims")).status_code == 200
        assert (await c.get("/api/auth/me")).status_code == 200
        assert (await c.post("/api/auth/login", json={"email": "first@example.com", "password": "correct-password-123"})).status_code == 200


async def test_upload_validation_and_scope_controls(app):
    async with client(app) as c:
        claim_id = await make_claim(c)
        for name, data, expected in [("file.pdf", b"fake-pdf", 422), ("test.exe", b"exe", 422),
                                      ("empty.txt", b"", 422)]:
            result = await c.post(f"/api/claims/{claim_id}/documents", files={"file": (name, data)})
            assert result.status_code == expected
        result = await c.post(f"/api/claims/{claim_id}/chat", json={"question": "Diagnose my symptoms"})
        assert result.status_code == 422 and result.json()["code"] == "out_of_scope"
        assert (await c.post("/api/claims", json={"title": "x"}, headers={"origin": "https://evil.example"})).status_code == 403
        result = await c.post(f"/api/claims/{claim_id}/analyze")
        assert result.status_code == 422 and result.json()["code"] == "missing_evidence"


async def test_embedding_model_change_requires_reindex(app):
    async with client(app) as c:
        claim_id = await make_claim(c)
        doc = await upload(c, claim_id)
        await finish_jobs(app)
        app.state.settings.nvidia_embedding_model = "configured-new-embedding"
        result = await c.post(f"/api/claims/{claim_id}/analyze")
        assert result.status_code == 422 and "Reindex" in result.json()["detail"]
        assert (await c.post(f"/api/documents/{doc['id']}/retry")).status_code == 200
        await finish_jobs(app)
        async with app.state.db.sessions() as session:
            chunk = await session.scalar(select(Chunk))
            assert chunk.embedding_model == "configured-new-embedding"
        assert (await c.post(f"/api/claims/{claim_id}/analyze")).status_code == 200


async def test_admin_usage_real_attempt_logs_and_health(app):
    async with client(app) as c:
        async with app.state.db.sessions() as session:
            user = await session.scalar(select(User))
            user.role = "admin"
            await session.commit()
        claim_id = await make_claim(c)
        await upload(c, claim_id)
        await finish_jobs(app)
        result = (await c.get("/api/admin/usage")).json()
        assert result["mode"] == "quota" and result["cost"] is None
        assert result["requests"] == result["requests_today"] == 1
        async with app.state.db.sessions() as session:
            assert (await session.scalar(select(AIUsage))).provider == "nvidia"


async def test_demo_uses_real_pipeline_and_synthetic_documents(app):
    async with client(app) as c:
        result = await c.post("/api/demo")
        assert result.status_code == 201
        await finish_jobs(app)
        detail = (await c.get(f"/api/claims/{result.json()['id']}")).json()
        assert len(detail["documents"]) == 3
        assert all(d["status"] == "ready" for d in detail["documents"])
        assert not detail["analyses"]
        assert app.state.test_calls and all("input_type" in call for call in app.state.test_calls)


def test_local_pdf_and_image_avoid_unneeded_remote_inference(tmp_path):
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((50, 50), TEXT.replace("\n", " "), fontsize=8)
    path = tmp_path/"text.pdf"
    pdf.save(path)
    pdf.close()
    pages = extract_local(path, "application/pdf", 50)
    assert pages[0]["method"] == "pymupdf" and not pages[0]["needs_vision"]
    image = Image.new("RGB", (100,100), "white")
    image.save(tmp_path/"scan.png")
    assert extract_local(tmp_path/"scan.png", "image/png", 50)[0]["needs_vision"]
    with pytest.raises(ValueError, match="1 to"):
        extract_local(path, "application/pdf", 0)


def test_chunking_keeps_exact_source_and_local_fields():
    text = TEXT*100
    chunks = chunk_text(text)
    assert len(chunks) > 1 and all(piece in text and len(piece) <= 1600 for piece in chunks)
    assert local_metadata(TEXT).document_type == "DENIAL_LETTER"


async def test_invalid_citation_never_persisted(app):
    async with client(app) as c:
        claim_id = await make_claim(c)
        await upload(c, claim_id)
        await finish_jobs(app)
        def bad_handler(request):
            body = json.loads(request.content)
            if "input" in body:
                return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1, 0.5, 0.3]}]})
            value = {"findings": [{"statement": "Invented fact", "kind": "fact",
                "citations": [{"chunk_id": "unknown", "quote": "a fabricated quote"}]}],
                "recommendations": [], "appeal_paragraphs": [], "missing_information": [], "insufficient_evidence": False}
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})
        app.state.ai.provider.client._transport = httpx.MockTransport(bad_handler)
        report = await c.post(f"/api/claims/{claim_id}/analyze")
        assert report.status_code == 503 and report.json()["code"] == "unverified_evidence"
        async with app.state.db.sessions() as session:
            assert await session.scalar(select(Analysis)) is None


def test_ocr_keeps_field_line_boundaries(tmp_path, monkeypatch):
    path = tmp_path / "image.png"
    Image.new("RGB", (200,200), "white").save(path)
    tokens = ["Claim", "ID:", "ABC-123", "Insurer:", "Example", "Health", "Denial", "reason:",
              "Authorization", "record", "is", "missing"]
    lines = [1,1,1,2,2,2,3,3,3,3,3,3]
    monkeypatch.setattr("app.services.documents.pytesseract.image_to_data", lambda *args, **kwargs:
        {"text": tokens, "conf": [95]*len(tokens), "block_num": [1]*len(tokens),
         "par_num": [1]*len(tokens), "line_num": lines})
    result = ocr_page(path, "image/png", 1)
    assert not result["needs_vision"]
    assert local_metadata(result["text"]).fields["claim_id"] == "ABC-123"
    assert local_metadata(result["text"]).fields["insurer"] == "Example Health"


async def test_duplicate_concurrent_uploads_create_one_document(app):
    async with client(app) as c:
        claim_id = await make_claim(c)
        uploaded = await asyncio.gather(*[upload(c, claim_id) for _ in range(3)])
        assert len({doc["id"] for doc in uploaded}) == 1
        await finish_jobs(app)
        detail = (await c.get(f"/api/claims/{claim_id}")).json()
        assert len(detail["documents"]) == 1
        assert len(app.state.test_calls) == 1


async def test_semantic_reviewer_rejects_unsupported_conclusions(app):
    async with client(app) as c:
        claim_id = await make_claim(c)
        await upload(c, claim_id)
        await finish_jobs(app)
        previous_handler = app.state.ai.provider.client._transport.handler
        def handler(request):
            body = json.loads(request.content)
            if "messages" in body and "unsupported_indexes" in body["messages"][0]["content"]:
                return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
                    {"supported": False, "unsupported_indexes": [0]})}}]})
            return previous_handler(request)
        app.state.ai.provider.client._transport = httpx.MockTransport(handler)
        report = await c.post(f"/api/claims/{claim_id}/analyze")
        assert report.status_code == 503 and "semantic evidence check" in report.json()["detail"]
        async with app.state.db.sessions() as session:
            assert await session.scalar(select(Analysis)) is None


async def test_rejected_response_is_regenerated_and_verifier_receives_source_context(app):
    async with client(app) as c:
        claim_id = await make_claim(c)
        await upload(c, claim_id)
        await finish_jobs(app)
        previous_handler = app.state.ai.provider.client._transport.handler
        reject = True
        generation_count = 0
        def handler(request):
            nonlocal generation_count
            body = json.loads(request.content)
            if "messages" in body:
                if "unsupported_indexes" in body["messages"][0]["content"]:
                    verification = json.loads(body["messages"][-1]["content"])
                    assert verification["conclusions"]
                    assert verification["source_context"][0]["text"] == TEXT
                    assert verification["source_context"][0]["chunk_id"] == verification["conclusions"][0]["citations"][0]["chunk_id"]
                    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
                        {"supported": not reject, "unsupported_indexes": [0] if reject else []})}}]})
                generation_count += 1
            return previous_handler(request)
        app.state.ai.provider.client._transport = httpx.MockTransport(handler)
        path = f"/api/claims/{claim_id}/analyze"
        assert (await c.post(path)).status_code == 503
        reject = False
        response = await c.post(path)
        assert response.status_code == 200
        assert generation_count == 3  # Two bounded attempts failed; retry generated a fresh response.
        cached = await c.post(path)
        assert cached.json()["id"] == response.json()["id"] and generation_count == 3


async def test_grounded_appeal_without_separate_findings_is_valid(app):
    async with client(app) as c:
        claim_id = await make_claim(c)
        await upload(c, claim_id)
        await finish_jobs(app)
        previous_handler = app.state.ai.provider.client._transport.handler
        def handler(request):
            response = previous_handler(request)
            body = json.loads(request.content)
            if "messages" in body and "unsupported_indexes" not in body["messages"][0]["content"]:
                payload = response.json()
                value = json.loads(payload["choices"][0]["message"]["content"])
                value["appeal_paragraphs"], value["findings"] = value["findings"], []
                payload["choices"][0]["message"]["content"] = json.dumps(value)
                return httpx.Response(200, json=payload)
            return response
        app.state.ai.provider.client._transport = httpx.MockTransport(handler)
        response = await c.post(f"/api/claims/{claim_id}/appeal")
        assert response.status_code == 200
        assert response.json()["result"]["appeal_paragraphs"][0]["citations"]
        path = f"/api/analyses/{response.json()['id']}/appeal/download"
        export = await c.get(path)
        assert export.status_code == 200 and "attachment" in export.headers["content-disposition"]
        assert export.text.startswith("DRAFT — HUMAN REVIEW REQUIRED")
        assert "Source: denial.txt, page 1:" in export.text
        assert response.json()["result"]["appeal_paragraphs"][0]["citations"][0]["quote"] in export.text
        async with client(app, "other-export@example.com") as other:
            assert (await other.get(path)).status_code == 404
        await c.post("/api/auth/logout")
        assert (await c.get(path)).status_code == 401


async def test_grounding_correction_is_bounded_and_reverified_before_saving(app):
    async with client(app) as c:
        claim_id = await make_claim(c)
        await upload(c, claim_id)
        await finish_jobs(app)
        previous_handler = app.state.ai.provider.client._transport.handler
        reviews = 0
        generations = []
        def handler(request):
            nonlocal reviews
            body = json.loads(request.content)
            if "messages" in body:
                if "unsupported_indexes" in body["messages"][0]["content"]:
                    reviews += 1
                    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
                        {"supported": reviews > 1, "unsupported_indexes": [0] if reviews == 1 else []})}}]})
                generations.append(json.loads(body["messages"][-1]["content"]))
            return previous_handler(request)
        app.state.ai.provider.client._transport = httpx.MockTransport(handler)
        response = await c.post(f"/api/claims/{claim_id}/analyze")
        assert response.status_code == 200 and reviews == 2
        assert len(generations) == 2
        assert "verification_feedback" not in generations[0]
        assert "verification_feedback" in generations[1]
        assert generations[0]["evidence"] == generations[1]["evidence"]
        async with app.state.db.sessions() as session:
            assert await session.scalar(select(Analysis)) is not None


def test_vision_requires_transcription_field_but_allows_explicit_illegibility():
    with pytest.raises(ValidationError):
        VisionDocumentExtraction(document_type="UNKNOWN", confidence=0, warnings=["Unreadable"])
    result = VisionDocumentExtraction(document_type="UNKNOWN", confidence=0, text="", warnings=["Unreadable"])
    assert result.text == ""


async def test_absent_deadline_cannot_establish_timeliness_even_if_model_reviewer_accepts(app):
    async with client(app) as c:
        claim_id = await make_claim(c)
        await upload(c, claim_id)
        await finish_jobs(app)
        previous_handler = app.state.ai.provider.client._transport.handler
        def handler(request):
            response = previous_handler(request)
            body = json.loads(request.content)
            if "messages" in body and "unsupported_indexes" not in body["messages"][0]["content"]:
                payload = response.json()
                value = json.loads(payload["choices"][0]["message"]["content"])
                value["findings"][0]["statement"] = "Since no deadline is listed, this appeal is timely."
                value["findings"][0]["kind"] = "inference"
                payload["choices"][0]["message"]["content"] = json.dumps(value)
                return httpx.Response(200, json=payload)
            return response
        app.state.ai.provider.client._transport = httpx.MockTransport(handler)
        response = await c.post(f"/api/claims/{claim_id}/appeal")
        assert response.status_code == 503 and "timeliness" in response.json()["detail"]
        async with app.state.db.sessions() as session:
            assert await session.scalar(select(Analysis)) is None
