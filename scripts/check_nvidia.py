"""Live synthetic endpoint checks. Secrets and prompts are never printed.

Run from the repository root: python scripts/check_nvidia.py
Usage metadata is recorded locally because this check can precede database setup.
"""
import asyncio
import base64
import io
import json
import sys
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))

from app.ai.client import AIClient  # noqa: E402
from app.ai.providers.base import AIError  # noqa: E402
from app.ai.providers.nvidia import NvidiaProvider  # noqa: E402
from app.ai.router.model_router import TaskType  # noqa: E402
from app.config import Settings  # noqa: E402
from app.schemas import DocumentExtraction  # noqa: E402


class CheckResponse(BaseModel):
    status: Literal["ok"]


async def main():
    settings = Settings().model_copy(update={"nvidia_max_retries": 0})
    folder = root / "data/verification"
    folder.mkdir(parents=True, exist_ok=True)
    async def log(values):
        with (folder / "nvidia-live-usage.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(values, default=str) + "\n")
    provider = NvidiaProvider(settings, usage_sink=log)
    ai = AIClient(provider, settings)
    outcomes = []
    async def check(name, operation):
        try:
            result = await operation()
            record = {"check": name, "success": True, "model": result.model}
            if hasattr(result, "vectors"):
                record["dimension"] = len(result.vectors[0])
        except AIError as exc:
            record = {"check": name, "success": False, "code": exc.code, "http_status": exc.status,
                      "message": exc.message}
        except Exception as exc:
            record = {"check": name, "success": False, "error_type": type(exc).__name__}
        outcomes.append(record)
        print(json.dumps(record), flush=True)
    try:
        health = await provider.health_check()
        print(json.dumps({"check": "health", "configured": health["configured"],
                          "reachable": health["reachable"], "http_status": health.get("http_status")}), flush=True)
        config = ai.router.select_model(TaskType.EMBEDDING)
        for mode in ("passage", "query"):
            await check("embedding_" + mode, lambda mode=mode: provider.embed(
                ["Synthetic administrative document: authorization record missing."], mode, config,
                ai.context(TaskType.EMBEDDING, "setup-verification")))
        messages = [{"role": "system", "content": "This is a synthetic connectivity check. Return status ok."},
                    {"role": "user", "content": "Confirm the connection with the required JSON response."}]
        await check("fast_structured", lambda: ai.structured(TaskType.METADATA_EXTRACTION, messages,
                    CheckResponse, "setup-verification"))
        await check("reasoning_structured", lambda: ai.structured(TaskType.POLICY_REASONING, messages,
                    CheckResponse, "setup-verification"))
        if settings.enable_vision:
            image = Image.new("RGB", (1000, 450), "white")
            draw = ImageDraw.Draw(image)
            draw.multiline_text((35, 35), "SYNTHETIC TEST DOCUMENT\nClaim ID: TEST-1042\nInsurer: Example Health\n"
                                "Denial reason: Authorization record missing.\nThis is fictional test data.",
                                fill="black", font=ImageFont.load_default(size=28), spacing=16)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG")
            data_url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
            await check("vision_structured", lambda: ai.vision("Transcribe this synthetic document and extract "
                "claim fields, without inventing values.", data_url, DocumentExtraction, "setup-verification", "synthetic"))
    finally:
        await ai.responses.close()
        await provider.close()
    (folder / "nvidia-live-checks.json").write_text(json.dumps(outcomes, indent=2), encoding="utf-8")
    return 0 if all(record["success"] for record in outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
