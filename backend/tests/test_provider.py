import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel

from app.ai.cache import AsyncCache
from app.ai.client import AIClient
from app.ai.embeddings import NvidiaEmbeddingService
from app.ai.providers.base import AIError, RequestContext
from app.ai.providers.nvidia import NvidiaProvider
from app.ai.router.model_router import NvidiaModelRouter, TaskType
from app.config import Settings


def settings(**extra):
    return Settings(_env_file=None, app_env="test", nvidia_api_key="test-key", nvidia_max_retries=1,
                    nvidia_embedding_dimension=3, **extra)


def ctx(task=TaskType.CLAIM_DENIAL_ANALYSIS):
    return RequestContext(task=task, request_id="test-request", owner_id="tenant", claim_id="claim")


async def no_sleep(seconds):
    pass


def completion(text="OK"):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                                     "usage": {"prompt_tokens": 12, "completion_tokens": 4}})


@pytest.mark.parametrize("task", list(TaskType))
def test_routing(task):
    s = settings()
    config = NvidiaModelRouter(s).select_model(task)
    if task in NvidiaModelRouter.REASONING_TASKS:
        assert config.model == s.nvidia_reasoning_model
    elif task == TaskType.EMBEDDING:
        assert config.model == s.nvidia_embedding_model
    elif task == TaskType.VISION_DOCUMENT_ANALYSIS:
        assert config.model == s.nvidia_vision_model
    elif task == TaskType.SAFETY:
        assert config.model == s.nvidia_safety_model
    else:
        assert config.model == s.nvidia_fast_model


async def test_retries_and_fallback_logged_with_actual_model():
    logs, models = [], []
    s = settings(nvidia_reasoning_fallback_model="configured-fallback",
                 nvidia_model_parameters={"configured-fallback": {"seed": 7},
                     "nvidia/nemotron-3-super-120b-a12b": {"reasoning_budget": 512}})
    async def sink(log):
        logs.append(log)
    def handler(request):
        assert request.url.host == "integrate.api.nvidia.com"
        assert request.headers["authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        models.append(body["model"])
        if body["model"] == s.nvidia_reasoning_model:
            assert body["reasoning_budget"] == 512
            return httpx.Response(429)
        assert "reasoning_budget" not in body
        assert body["seed"] == 7
        return completion()
    provider = NvidiaProvider(s, sink, httpx.MockTransport(handler), no_sleep)
    config = NvidiaModelRouter(s).select_model(ctx().task)
    result = await provider.chat([{"role": "user", "content": "Hello"}], config, ctx())
    assert models == [s.nvidia_reasoning_model, s.nvidia_reasoning_model, "configured-fallback"]
    assert result.fallback_used and result.model == "configured-fallback"
    assert [log["http_status"] for log in logs] == [429, 429, 200]
    assert logs[-1]["fallback_used"] and logs[-1]["output_tokens"] == 4
    assert all("messages" not in log and "prompt" not in log for log in logs)
    await provider.close()


@pytest.mark.parametrize("status,code", [(401, "authentication"), (403, "authentication"),
    (400, "invalid_request"), (404, "model_unavailable"), (429, "rate_limit"), (503, "service_unavailable")])
async def test_status_errors(status, code):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status)
    s = settings()
    provider = NvidiaProvider(s, transport=httpx.MockTransport(handler), sleep=no_sleep)
    with pytest.raises(AIError) as exc:
        await provider.chat([{"role": "user", "content": "test"}], NvidiaModelRouter(s).select_model(ctx().task), ctx())
    assert exc.value.code == code
    assert len(calls) == (2 if exc.value.retryable else 1)
    assert "test-key" not in str(exc.value)
    await provider.close()


async def test_timeout_fallback():
    s = settings(nvidia_fast_fallback_model="fast-fallback")
    def handler(request):
        if json.loads(request.content)["model"] == s.nvidia_fast_model:
            raise httpx.ReadTimeout("simulated timeout", request=request)
        return completion()
    provider = NvidiaProvider(s, transport=httpx.MockTransport(handler), sleep=no_sleep)
    config = NvidiaModelRouter(s).select_model(TaskType.SIMPLE_QUESTION)
    assert (await provider.chat([{"role": "user", "content": "test"}], config, ctx())).model == "fast-fallback"
    await provider.close()


class Output(BaseModel):
    number: int


async def test_structured_repair_is_once_and_validated():
    responses = iter(["not JSON", '```json\n{"number": 2}\n```'])
    provider = NvidiaProvider(settings(), transport=httpx.MockTransport(lambda req: completion(next(responses))))
    result = await provider.structured_chat([{"role": "user", "content": "test"}], Output,
        NvidiaModelRouter(settings()).select_model(TaskType.METADATA_EXTRACTION), ctx())
    assert result.value.number == 2
    await provider.close()


async def test_malformed_structured_output_fails_safely():
    calls = []
    def handler(request):
        calls.append(request)
        return completion('{"number": "invalid"}')
    provider = NvidiaProvider(settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(AIError, match="could not be validated"):
        await provider.structured_chat([{"role": "user", "content": "test"}], Output,
            NvidiaModelRouter(settings()).select_model(TaskType.METADATA_EXTRACTION), ctx())
    assert len(calls) == 2
    await provider.close()


async def test_embedding_modes_batch_order_and_cache():
    bodies = []
    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [1, i, 0.5]}
                                                  for i in reversed(range(len(body["input"])))]})
    s = settings()
    provider = NvidiaProvider(s, transport=httpx.MockTransport(handler))
    service = NvidiaEmbeddingService(AIClient(provider, s))
    assert len(await service.passage_embeddings(["one", "two", "three"], "tenant", "claim")) == 3
    await service.passage_embeddings(["one", "two", "three"], "tenant", "claim")
    await service.query_embedding("one", "tenant", "claim")
    assert [body["input_type"] for body in bodies] == ["passage", "query"]
    assert len(bodies[0]["input"]) == 3
    await service.query_embedding("one", "another-tenant", "claim")
    assert len(bodies) == 3
    await provider.close()


@pytest.mark.parametrize("vector", [[1, 2], [0, 0, 0], [1, float("inf"), 3], [True, 1, 3]])
async def test_embedding_validation(vector):
    provider = NvidiaProvider(settings(), transport=httpx.MockTransport(lambda req:
        httpx.Response(200, content=json.dumps({"data": [{"index": 0, "embedding": vector}]}))))
    with pytest.raises(AIError, match="incompatible"):
        await provider.embed(["passage"], "passage", NvidiaModelRouter(settings()).select_model(TaskType.EMBEDDING), ctx())
    await provider.close()


async def test_singleflight_concurrent_and_failure_not_cached():
    cache = AsyncCache()
    calls = 0
    async def factory():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return "value"
    assert await asyncio.gather(*[cache.get_or_create("key", factory) for _ in range(10)]) == ["value"]*10
    assert calls == 1
    async def fails():
        raise AIError("error")
    for _ in range(2):
        with pytest.raises(AIError):
            await cache.get_or_create("failure", fails)
    assert "failure" not in cache.values


async def test_vision_does_not_count_base64_as_text():
    s = settings()
    provider = NvidiaProvider(s, transport=httpx.MockTransport(lambda req: completion('{"number": 1}')))
    result = await provider.vision("Extract fields", "data:image/jpeg;base64," + "a"*100000, Output,
                                  NvidiaModelRouter(s).select_model(TaskType.VISION_DOCUMENT_ANALYSIS), ctx())
    assert result.value.number == 1
    await provider.close()


async def test_health_never_exposes_secret_and_safety_is_optional():
    s = settings(enable_nvidia_safety=True, nvidia_safety_model="optional-safety")
    def handler(request):
        return httpx.Response(200, json={"data": []}) if request.method == "GET" else httpx.Response(503)
    provider = NvidiaProvider(s, transport=httpx.MockTransport(handler), sleep=no_sleep)
    assert "test-key" not in json.dumps(await provider.health_check())
    assert await AIClient(provider, s).safety_check("review documents", "tenant", "claim")
    await provider.close()


def test_reject_wrong_provider_and_secret_override():
    with pytest.raises(ValueError):
        Settings(_env_file=None, ai_provider="other")
    with pytest.raises(ValueError):
        Settings(_env_file=None, nvidia_base_url="https://example.org")
    with pytest.raises(ValueError):
        Settings(_env_file=None, nvidia_model_parameters={"model": {"messages": []}})


async def test_disconnect_does_not_cancel_shared_request():
    cache = AsyncCache()
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0
    async def factory():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return "result"
    first = asyncio.create_task(cache.get_or_create("shared", factory))
    await started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(cache.get_or_create("shared", factory))
    release.set()
    assert await second == "result" and calls == 1


async def test_truncated_completion_is_rejected():
    s = settings()
    provider = NvidiaProvider(s, transport=httpx.MockTransport(lambda req: httpx.Response(200,
        json={"choices": [{"message": {"content": "partial text"}, "finish_reason": "length"}]})))
    with pytest.raises(AIError) as exc:
        await provider.chat([{"role": "user", "content": "test"}],
                            NvidiaModelRouter(s).select_model(TaskType.POLICY_REASONING), ctx())
    assert exc.value.code == "output_limit"
    await provider.close()
