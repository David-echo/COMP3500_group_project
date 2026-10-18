"""
SSE 实时推送 (Server-Sent Events) —— 成员 4 负责
==============================================

对应团队要求：「SSE 实现页面实时显示投票结果」。

⚠️ 重要设计约束（写进 SRS / 报告）：
  - **投票进行中**只推送 **投票率（turnout）**，聚合值，不影响公平；
  - **各候选人票数**只能在选举截止后推送（results 频道）。
    真实选举中公布实时票数会引导后续投票行为，损害公平性。

浏览器端：
    const es = new EventSource('/api/v1/events/turnout?electionId=1')
    es.addEventListener('turnout', e => console.log(JSON.parse(e.data)))
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from ..config import get_settings
from ..services import pubsub

router = APIRouter(prefix="/events", tags=["实时推送"])

_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # 让 Nginx 不缓冲 SSE
}


def _format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream(channel: str, event_name: str, election_id: int | None) -> AsyncIterator[str]:
    """转发频道消息，并定期发心跳防止连接被中间层断开。"""
    heartbeat = get_settings().sse_heartbeat_seconds
    queue: asyncio.Queue = asyncio.Queue()
    pub = pubsub.get_pubsub()

    async def forward() -> None:
        async for msg in pub.subscribe(channel):
            if election_id is None or msg.get("electionId") == election_id:
                await queue.put(msg)

    task = asyncio.create_task(forward())
    try:
        # 首帧：告诉前端连接已建立
        yield _format("open", {"channel": channel, "electionId": election_id})
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=heartbeat)
                yield _format(event_name, msg)
            except asyncio.TimeoutError:
                yield _format("heartbeat", {"ts": asyncio.get_event_loop().time()})
    finally:
        task.cancel()


@router.get("/turnout")
async def events_turnout(
    election_id: int | None = Query(default=None, alias="electionId")
):
    return StreamingResponse(
        _stream(pubsub.CHANNEL_TURNOUT, "turnout", election_id),
        media_type="text/event-stream",
        headers=_HEADERS,
    )


@router.get("/results")
async def events_results(
    election_id: int | None = Query(default=None, alias="electionId")
):
    return StreamingResponse(
        _stream(pubsub.CHANNEL_RESULTS, "results", election_id),
        media_type="text/event-stream",
        headers=_HEADERS,
    )
