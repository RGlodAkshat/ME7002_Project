import asyncio
from typing import Any

from fastapi import WebSocket


class EventBroadcaster:
    def __init__(self) -> None:
        self.connections: list[WebSocket] = []
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self.lock:
            self.connections.append(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self.lock:
            if websocket in self.connections:
                self.connections.remove(websocket)

    async def publish(self, event: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for websocket in list(self.connections):
            try:
                await websocket.send_json(event)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            await self.disconnect(websocket)


broadcaster = EventBroadcaster()
