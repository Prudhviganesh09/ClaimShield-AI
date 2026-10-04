import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any


def cache_key(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


class AsyncCache:
    """Bounded, process-local TTL cache and single-flight. Keys include tenant and model configuration."""

    def __init__(self, max_entries: int = 128, ttl: float = 900):
        self.max_entries, self.ttl = max_entries, ttl
        self.values: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self.inflight: dict[str, asyncio.Task] = {}

    async def get_or_create(self, key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
        now = time.monotonic()
        if key in self.values:
            expiry, value = self.values[key]
            if expiry > now:
                self.values.move_to_end(key)
                return value
            del self.values[key]
        if key in self.inflight:
            return await asyncio.shield(self.inflight[key])

        async def compute():
            try:
                value = await factory()
                self.values[key] = (time.monotonic() + self.ttl, value)
                while len(self.values) > self.max_entries:
                    self.values.popitem(last=False)
                return value
            finally:
                self.inflight.pop(key, None)

        task = asyncio.create_task(compute())
        self.inflight[key] = task
        # Consume exceptions if every waiting caller disconnects.
        task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        return await asyncio.shield(task)

    async def close(self):
        tasks = list(self.inflight.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.values.clear()
