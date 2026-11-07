"""Module."""
from __future__ import annotations
import asyncio
import json
from typing import AsyncIterator
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from ..config import get_settings
from ..services import pubsub
router = APIRouter(prefix="/events", tags=["Live updates"])
_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
def _format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
async def _stream(channel: str, event_name: str, election_id: int | None) -> AsyncIterator[str]:
    """Stream."""
    heartbeat = get_settings().sse_heartbeat_seconds
    queue: asyncio.Queue = asyncio.Queue()
    pub = pubsub.get_pubsub()
    async def forward() -> None:
        async for msg in pub.subscribe(channel):
            if election_id is None or msg.get("election_id") == election_id:
                await queue.put(msg)
    task = asyncio.create_task(forward())
    try:
        yield _format("open", {"channel": channel, "election_id": election_id})
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
    election_id: int | None = Query(default=None)
):
    return StreamingResponse(
        _stream(pubsub.CHANNEL_TURNOUT, "turnout", election_id),
        media_type="text/event-stream",
        headers=_HEADERS,
    )
@router.get("/results")
async def events_results(
    election_id: int | None = Query(default=None)
):
    return StreamingResponse(
        _stream(pubsub.CHANNEL_RESULTS, "results", election_id),
        media_type="text/event-stream",
        headers=_HEADERS,
    )
