"""Real-time layer: persists notifications and pushes events over WebSocket.

Every message on the socket has the same envelope:

    {"event": "<name>", "data": {...}, "sent_at": "<ISO-8601 UTC>"}

Events:
    notification          a new notification was stored for this user
    notifications_read    notifications were marked read (keeps other tabs' badges in sync)
    order_status_updated  an order's order_status or payment_status changed —
                          sent to the order's owner and to every staff/admin
    cart_updated          the user's cart changed (add/update/remove/checkout)
    pong                  reply to a client "ping"
"""
import asyncio
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from ..models import Notification, NotificationType, Order


class ConnectionManager:
    """Tracks open WebSocket connections per user id, plus each user's role so
    operational events can fan out to staff/admin."""

    STAFF_ROLES = ("admin", "staff")

    def __init__(self) -> None:
        self._connections: Dict[int, List[WebSocket]] = {}
        self._roles: Dict[int, str] = {}
        # The server's event loop, captured at startup — needed because sync
        # endpoints run in a worker thread where no loop is running.
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    async def connect(self, user_id: int, role: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(user_id, []).append(websocket)
        self._roles[user_id] = role

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        sockets = self._connections.get(user_id, [])
        if websocket in sockets:
            sockets.remove(websocket)
        if not sockets:
            self._connections.pop(user_id, None)
            self._roles.pop(user_id, None)

    def staff_user_ids(self) -> List[int]:
        return [uid for uid, role in self._roles.items() if role in self.STAFF_ROLES]

    def is_connected(self, user_id: int) -> bool:
        return bool(self._connections.get(user_id))

    async def push(self, user_ids: Iterable[int], message: dict) -> None:
        for user_id in set(user_ids):
            for ws in list(self._connections.get(user_id, [])):
                try:
                    await ws.send_json(message)
                except Exception:
                    self.disconnect(user_id, ws)


manager = ConnectionManager()


def envelope(event: str, data: dict) -> dict:
    return {
        "event": event,
        "data": jsonable_encoder(data),
        "sent_at": datetime.utcnow().isoformat() + "Z",
    }


def publish(user_ids: Iterable[int], event: str, data: dict, include_staff: bool = False) -> None:
    """Push an event to these users' open sockets. Never raises and never
    blocks: callers are request handlers, and a missing listener is normal."""
    loop = manager.loop
    if loop is None or not loop.is_running():
        return
    targets = set(user_ids)
    message = envelope(event, data)

    async def _send():
        # Resolved on the loop thread, where the connection table lives.
        recipients = targets | (set(manager.staff_user_ids()) if include_staff else set())
        await manager.push(recipients, message)

    # Sync endpoints run in a worker thread — hand the push to the server's
    # event loop thread-safely.
    asyncio.run_coroutine_threadsafe(_send(), loop)


def notification_payload(notification: Notification) -> dict:
    return {
        "id": notification.id,
        "type": notification.type,
        "title": notification.title,
        "message": notification.message,
        "order_id": notification.order_id,
        "is_read": notification.is_read,
        "read_status": notification.is_read,
        "created_at": notification.created_at,
        "timestamp": notification.created_at,
    }


def notify(
    db: Session,
    user_id: int,
    type_: str,
    title: str,
    message: str,
    order_id: Optional[int] = None,
) -> Notification:
    """Persist a notification and push it to the user's open sockets (if any)."""
    if isinstance(type_, NotificationType):
        type_ = type_.value
    notification = Notification(
        user_id=user_id, type=type_, title=title, message=message, order_id=order_id
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    publish([user_id], "notification", notification_payload(notification))
    return notification


def publish_order_status(order: Order, previous_status: Optional[str] = None) -> None:
    """order_status_updated → the order's owner, plus every connected staff/admin
    (their all-orders views and the analytics dashboard refresh on it)."""
    publish(
        [order.user_id],
        "order_status_updated",
        {
            "order_id": order.id,
            "order_number": order.order_number,
            "user_id": order.user_id,
            "order_status": order.order_status.value,
            "previous_status": previous_status,
            "payment_status": order.payment_status.value,
            "total": order.total,
            "allowed_next_statuses": order.allowed_next_statuses,
        },
        include_staff=True,
    )


def publish_cart(user_id: int, cart, reason: str) -> None:
    """cart_updated → the cart owner's other tabs/devices."""
    data = cart.model_dump() if hasattr(cart, "model_dump") else dict(cart)
    data["reason"] = reason
    publish([user_id], "cart_updated", data)
