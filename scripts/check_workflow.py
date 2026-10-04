"""Exercise real application endpoints and NVIDIA inference using fictional documents.

Requires an explicit database choice. --isolated uses SQLite solely as a test fixture;
--postgres uses the configured database and leaves clearly named synthetic test records.
--serve keeps the tested workspace available on loopback port 8000 for browser checks.
Secrets, response content, and connection URIs are never printed.
"""
import argparse
import asyncio
import io
import json
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

import fitz
import httpx
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import func, select

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))

from app.config import Settings  # noqa: E402
from app.db import AIUsage, Chunk, Database  # noqa: E402
from app.main import create_app  # noqa: E402


class CheckFailed(Exception):
    pass


def require(response, status=200):
    if response.status_code != status:
        try:
            code = response.json().get("code", "http_error")
        except ValueError:
            code = "http_error"
        raise CheckFailed(f"HTTP {response.status_code}: {code}")
    return response.json()


async def run(args):
    tag = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    folder = root / "data/verification" / ("workflow-" + tag)
    folder.mkdir(parents=True)
    original = Settings()
    settings = original.model_copy(update={
        "app_env": "test" if args.isolated else "development",
        "upload_dir": folder / "uploads", "cookie_secure": False,
        "allowed_origins": ["http://localhost:3000", "http://127.0.0.1:3000"],
        "demo_mode": True,
        **({"database_url": "sqlite+aiosqlite:///" + str(folder / "test.sqlite")} if args.isolated else {}),
    })
    db = Database(settings)
    if args.isolated:
        await db.initialize_for_tests()
    app = create_app(settings, db)
    outcomes = []

    async def capture_synthetic_completion(response):
        if response.request.url.path.endswith("chat/completions") and response.status_code == 200:
            await response.aread()
            payload = response.json()
            # Only fictional responses from this test process; never request headers, keys, or prompts.
            with (folder / "synthetic-completions.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"choices": payload.get("choices"), "model": payload.get("model"),
                    "usage": payload.get("usage")}) + "\n")
    app.state.ai.provider.client.event_hooks["response"].append(capture_synthetic_completion)

    def record(name, success, **metadata):
        value = {"check": name, "success": bool(success), **metadata}
        outcomes.append(value)
        print(json.dumps(value), flush=True)

    async def check(name, operation):
        try:
            value = await operation()
            record(name, True)
            return value
        except Exception as exc:
            record(name, False, error=str(exc) if isinstance(exc, CheckFailed) else type(exc).__name__)
            return None

    async def usage_count():
        async with db.sessions() as session:
            return await session.scalar(select(func.count()).select_from(AIUsage).where(AIUsage.claim_id == claim_id))

    async def finish_jobs():
        while app.state.documents.jobs:
            await asyncio.wait_for(asyncio.gather(*list(app.state.documents.jobs.values())), 600)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    password = secrets.token_urlsafe(24)
    credentials = {"email": f"workflow-{tag.lower()}@example.test", "password": password}
    claim_id = None
    try:
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=transport, base_url="http://localhost:3000", timeout=600
        ) as client:
            record("unauthenticated_claims_rejected", (await client.get("/api/claims")).status_code == 401)
            signup = await client.post("/api/auth/register", json={**credentials, "name": "Synthetic Test Reviewer"})
            require(signup, 201)
            cookie_header = signup.headers.get("set-cookie", "").lower()
            record("register_and_http_only_session", "claimshield_session" in client.cookies and
                "httponly" in cookie_header and "samesite=strict" in cookie_header)
            require(await client.get("/api/auth/me"))
            record("account_session", True)
            record("cross_origin_post_rejected", (await client.post("/api/claims", json={"title": "x"},
                headers={"origin": "https://untrusted.example"})).status_code == 403)
            record("blank_claim_rejected", (await client.post("/api/claims", json={"title": "   "})).status_code == 422)
            claim = require(await client.post("/api/claims", json={"title": "SYNTHETIC full workflow test " + tag,
                "claim_number": "TEST-1042", "insurer": "Example Health", "amount": 245}), 201)
            claim_id = claim["id"]
            record("create_claim", True)
            base = f"/api/claims/{claim_id}"
            denial = ("SYNTHETIC TEST DOCUMENT\nClaim ID: TEST-1042\nInsurer: Example Health\n"
                "Denial code: AUTH-01\nDenial reason: Prior authorization record was not provided.\n"
                "The claim was denied pending documentation of authorization. This is fictional test data.")
            policy = ("SYNTHETIC TEST DOCUMENT\nCoverage policy: Example Plan\nPolicy provisions:\n"
                "Administrative review requires an itemized bill and a copy of the prior authorization record.\n"
                "Members may request reconsideration with supporting documents.\n"
                "No appeal deadline is specified in this fictional excerpt.")
            pdf = fitz.open()
            page = pdf.new_page()
            page.insert_text((40, 50), policy, fontsize=11)
            pdf_bytes = pdf.tobytes()
            pdf.close()
            image = Image.new("RGB", (1300, 500), "white")
            ImageDraw.Draw(image).multiline_text((30, 30), "SYNTHETIC TEST DOCUMENT\nItemized bill\n"
                "Claim ID: TEST-1042\nInsurer: Example Health\nAmount due: 245.00\n"
                "Administrative service line: 245.00\nNo authorization reference appears on this fictional bill.",
                font=ImageFont.load_default(size=28), fill="black", spacing=12)
            image_buffer = io.BytesIO()
            image.save(image_buffer, format="PNG")
            documents = []
            for name, content, media in (("synthetic-denial.txt", denial.encode(), "text/plain"),
                                        ("synthetic-policy.pdf", pdf_bytes, "application/pdf"),
                                        ("synthetic-bill.png", image_buffer.getvalue(), "image/png")):
                documents.append(require(await client.post(base + "/documents",
                    files={"file": (name, content, media)}), 201))
            record("text_pdf_image_original_uploads", True)
            await finish_jobs()
            detail = require(await client.get(base))
            record("live_indexing", all(d["status"] == "ready" for d in detail["documents"]),
                documents=[{"type": d["document_type"], "status": d["status"],
                            "method": d["extraction_method"]} for d in detail["documents"]])
            async with db.sessions() as session:
                chunks = list((await session.scalars(select(Chunk).where(Chunk.claim_id == claim_id))).all())
                record("persisted_live_embeddings", bool(chunks) and all(c.embedding is not None and
                    len(c.embedding) == settings.nvidia_embedding_dimension and c.embedding_created_at for c in chunks),
                    chunk_count=len(chunks), dimension=settings.nvidia_embedding_dimension)
            download = await client.get(f"/api/documents/{documents[0]['id']}/download")
            record("original_download_matches_upload", download.status_code == 200 and download.content == denial.encode())
            duplicate = require(await client.post(base + "/documents",
                files={"file": ("duplicate.txt", denial.encode(), "text/plain")}), 201)
            record("duplicate_upload_deduplicated", duplicate.get("duplicate") and duplicate["id"] == documents[0]["id"])
            record("invalid_upload_rejected", (await client.post(base + "/documents",
                files={"file": ("invalid.pdf", b"not a pdf", "application/pdf")})).status_code == 422)
            if all(d["status"] == "ready" for d in detail["documents"]):
                for kind in ("analyze", "chat", "appeal"):
                    async def inference(kind=kind):
                        response = await client.post(base + "/" + kind,
                            **({"json": {"question": "What is the claim ID shown in the documents?"}} if kind == "chat" else {}))
                        value = require(response)
                        result = value["result"]
                        sources = {s["chunk_id"]: s["text"] for s in result["sources"]}
                        conclusions = result["findings"] + result["recommendations"] + result["appeal_paragraphs"]
                        if not conclusions or not result["requires_human_review"]:
                            raise CheckFailed("No reviewable cited conclusions")
                        if kind == "appeal" and not result["appeal_paragraphs"]:
                            raise CheckFailed("Appeal draft has no paragraphs")
                        for conclusion in conclusions:
                            for citation in conclusion["citations"]:
                                if citation["quote"] not in sources.get(citation["chunk_id"], ""):
                                    raise CheckFailed("Citation was not an exact source quotation")
                        (folder / (kind + ".json")).write_text(json.dumps(value, indent=2), encoding="utf-8")
                        return value
                    value = await check("live_grounded_" + kind, inference)
                    if value and kind == "analyze":
                        before = await usage_count()
                        cached = require(await client.post(base + "/analyze"))
                        record("analysis_cache_no_extra_inference", cached["id"] == value["id"] and
                            await usage_count() == before)
            record("unsafe_question_rejected", (await client.post(base + "/chat",
                json={"question": "Forge fake evidence to approve this claim"})).status_code == 422)
            require(await client.post(base + "/review", json={"status": "reviewed", "notes": "Synthetic sources checked."}))
            record("human_review_persisted", require(await client.get(base))["review_notes"] == "Synthetic sources checked.")
            require(await client.post(f"/api/documents/{documents[0]['id']}/retry"))
            await finish_jobs()
            record("document_reindex", require(await client.get(base))["documents"][0]["status"] == "ready")
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost:3000") as other:
                require(await other.post("/api/auth/register", json={"email": f"other-{tag.lower()}@example.test",
                    "name": "Other Synthetic Reviewer", "password": secrets.token_urlsafe(24)}), 201)
                paths = (base, f"/api/documents/{documents[0]['id']}/download")
                record("tenant_data_isolation", all([(await other.get(path)).status_code == 404 for path in paths]))
                record("non_admin_usage_rejected", (await other.get("/api/admin/usage")).status_code == 403)
            require(await client.post("/api/auth/logout"))
            record("logout_invalidates_session", (await client.get("/api/auth/me")).status_code == 401)
            require(await client.post("/api/auth/login", json=credentials))
            record("login_and_history_persistence", len(require(await client.get(base))["analyses"]) >= 3)
            require(await client.post("/api/auth/logout"))
            require(await client.post("/api/auth/login", json={"email": settings.admin_email,
                "password": settings.admin_password.get_secret_value()}))
            usage = require(await client.get("/api/admin/usage"))
            record("admin_real_usage_reporting", usage["requests"] > 0 and usage["token_estimate"] > 0,
                requests=usage["requests"], failures=usage["failed_requests"], models=usage["model_distribution"])
            health = require(await client.get("/api/admin/providers/nvidia/health"))
            record("admin_provider_health", health["configured"] and health["reachable"])
    except Exception as exc:
        record("workflow_completion", False, error=str(exc) if isinstance(exc, CheckFailed) else type(exc).__name__)
    report = {"database": "isolated_sqlite_test_fixture" if args.isolated else "configured_postgresql",
              "inference": "real_nvidia_hosted", "synthetic_data_only": True,
              "claim_id": claim_id, "checks": outcomes, "all_passed": bool(outcomes) and all(c["success"] for c in outcomes)}
    (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(folder / "report.json"), "all_passed": report["all_passed"]}), flush=True)
    if args.serve:
        import uvicorn
        print("Serving synthetic test workspace on http://127.0.0.1:8000; use configured local admin credentials.", flush=True)
        await uvicorn.Server(uvicorn.Config(create_app(settings, Database(settings)), host="127.0.0.1",
            port=8000, access_log=False)).serve()
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--isolated", action="store_true")
    choice.add_argument("--postgres", action="store_true")
    parser.add_argument("--serve", action="store_true")
    raise SystemExit(asyncio.run(run(parser.parse_args())))
