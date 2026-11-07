"""Module."""
from __future__ import annotations
import asyncio
import json
from typing import Any, AsyncIterator, Protocol
from ..config import get_settings
class PubSub(Protocol):
    async def publish(self, channel: str, message: dict[str, Any]) -> None: ...
    def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]: ...
# ==========================================================================
# ==========================================================================
class InMemoryPubSub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        for q in list(self._subscribers.get(channel, ())):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await q.put(message)
    async def _stream(self, channel: str) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.setdefault(channel, set()).add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers.get(channel, set()).discard(q)
    def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]:
        return self._stream(channel)
# ==========================================================================
# ==========================================================================
class RedisPubSub:
    def __init__(self, url: str) -> None:
        import redis.asyncio as redis
        self._redis = redis.from_url(url, decode_responses=True)
    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        await self._redis.publish(channel, json.dumps(message, ensure_ascii=False))
    async def _stream(self, channel: str) -> AsyncIterator[dict[str, Any]]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for msg in pubsub.listen():
                if msg.get("type") == "message":
                    yield json.loads(msg["data"])
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
    def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]:
        return self._stream(channel)
# ==========================================================================
# ==========================================================================
_pubsub: PubSub | None = None
def get_pubsub() -> PubSub:
    global _pubsub
    if _pubsub is None:
        url = get_settings().redis_url
        _pubsub = RedisPubSub(url) if url else InMemoryPubSub()
    return _pubsub
def reset_pubsub() -> None:
    """Reset pubsub."""
    global _pubsub
    _pubsub = None
CHANNEL_TURNOUT = "turnout"
CHANNEL_RESULTS = "results"
