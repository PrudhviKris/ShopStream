"""Real-time notifications: persists to DB and pushes over WebSocket if connected."""
import asyncio
from typing import Dict, List

from fastapi import WebSocket
from sqlalchemy.orm import Session

from ..models import Notification


class ConnectionManager:
    """Tracks open WebSocket connections per user id."""

    def __init__(self) -> None:
        self._connections: Dict[int, List[WebSocket]] = {}
        # The server's event loop, captured at startup — needed because sync
        # endpoints run in a worker thread where no loop is running.
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(user_id, []).append(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        sockets = self._connections.get(user_id, [])
        if websocket in sockets:
            sockets.remove(websocket)
        if not sockets:
            self._connections.pop(user_id, None)

    async def push(self, user_id: int, payload: dict) -> None:
        for ws in list(self._connections.get(user_id, [])):
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect(user_id, ws)


manager = ConnectionManager()


def notify(db: Session, user_id: int, type_: str, title: str, message: str) -> Notification:
    """Persist a notification and push it to the user's open sockets (if any)."""
    notification = Notification(
        user_id=user_id, type=type_, title=title, message=message
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)

    payload = {
        "id": notification.id,
        "type": notification.type,
        "title": notification.title,
        "message": notification.message,
        "created_at": notification.created_at.isoformat(),
    }
    if manager.loop is not None and manager.loop.is_running():
        # Called from a sync endpoint (worker thread) — hand the push to the
        # server's event loop thread-safely.
        asyncio.run_coroutine_threadsafe(manager.push(user_id, payload), manager.loop)
    return notification
