"""
发布订阅 (Pub/Sub) —— 支撑 SSE 实时推送
======================================

设计（对应 Lecture 6 的架构决策）：
  - 生产：Redis Pub/Sub，多实例部署时各实例都能收到事件
  - 开发：进程内 asyncio 队列，单实例即可演示，**不需要装 Redis**

抽象成同一接口 Benefits：
业务代码只调用 publish()/subscribe()，不关心后端是 Redis 还是内存，
这也是"层接口变化只影响相邻层"的体现。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Protocol

from ..config import get_settings


class PubSub(Protocol):
    async def publish(self, channel: str, message: dict[str, Any]) -> None: ...
    def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]: ...


# ==========================================================================
# 进程内实现（默认，无需外部服务）
# ==========================================================================

class InMemoryPubSub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        for q in list(self._subscribers.get(channel, ())):
            # 队列满时丢弃旧事件，避免慢消费者拖垮发布者
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
# Redis 实现（生产）
# ==========================================================================

class RedisPubSub:
    def __init__(self, url: str) -> None:
        import redis.asyncio as redis  # 延迟导入：未装 redis 时不影响开发

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
# 工厂
# ==========================================================================

_pubsub: PubSub | None = None


def get_pubsub() -> PubSub:
    global _pubsub
    if _pubsub is None:
        url = get_settings().redis_url
        _pubsub = RedisPubSub(url) if url else InMemoryPubSub()
    return _pubsub


def reset_pubsub() -> None:
    """测试用：重置单例。"""
    global _pubsub
    _pubsub = None


# 频道名约定
CHANNEL_TURNOUT = "turnout"     # 投票率（投票期间可公开）
CHANNEL_RESULTS = "results"     # 各候选人票数（仅截止后）
