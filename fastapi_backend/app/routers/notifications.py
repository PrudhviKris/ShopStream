from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import false
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..deps import get_current_user
from ..models import Notification, NotificationType, User
from ..schemas import (
    NotificationOut,
    NotificationReadRequest,
    NotificationReadResult,
    UnreadCount,
)
from ..security import decode_token
from ..services.notification_service import envelope, manager, publish

router = APIRouter(tags=["Notifications"])


def _unread_count(db: Session, user_id: int) -> int:
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read.is_(False))
        .count()
    )


@router.get("/notifications", response_model=List[NotificationOut])
def list_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    unread_only: bool = Query(default=False, description="Only notifications not yet read."),
    type: Optional[NotificationType] = Query(default=None, description="Only this kind of event."),
    limit: int = Query(default=100, ge=1, le=500),
):
    """The signed-in user's notifications, newest first.

    Types: `order_placed`, `order_confirmed`, `payment_successful`,
    `payment_failed`, `order_shipped`, `order_delivered`, `order_cancelled`.
    """
    query = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))
    if type is not None:
        query = query.filter(Notification.type == type.value)
    return query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all()


@router.get("/notifications/unread-count", response_model=UnreadCount)
def unread_count(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"unread_count": _unread_count(db, user.id)}


@router.post("/notifications/read", response_model=NotificationReadResult)
def mark_notifications_read(
    body: Optional[NotificationReadRequest] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark notifications as read.

    * `{"notification_ids": [12, 13]}` — just those
    * `{"all": true}` or an empty body — every unread notification

    Only ever touches the caller's own notifications; ids belonging to someone
    else are ignored. Other open tabs get a `notifications_read` WebSocket
    event so their unread badge updates too.
    """
    query = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read.is_(False)
    )
    # Explicit ids (even an empty list, which marks nothing) take precedence
    # unless `all` is set; no body at all means "everything".
    ids = body.notification_ids if body is not None and not body.all else None
    if ids is not None:
        query = query.filter(Notification.id.in_(ids)) if ids else query.filter(false())
    marked = query.update({Notification.is_read: True}, synchronize_session=False)
    db.commit()

    remaining = _unread_count(db, user.id)
    if marked:
        publish([user.id], "notifications_read",
                {"notification_ids": ids if ids is not None else "all", "unread_count": remaining})
    return {"marked_read": marked, "unread_count": remaining}


@router.put("/notifications/{notification_id}/read", response_model=NotificationOut, deprecated=True)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Deprecated — use `POST /notifications/read` with `{"notification_ids": [id]}`."""
    notification = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user.id)
        .first()
    )
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return notification


@router.put("/notifications/read-all", deprecated=True)
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Deprecated — use `POST /notifications/read` with `{"all": true}`."""
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.is_read.is_(False))
        .update({Notification.is_read: True})
    )
    db.commit()
    return {"marked_read": updated}


@router.websocket("/ws/notifications")
async def notifications_ws(websocket: WebSocket, token: str = Query(...)):
    """Real-time event stream for the signed-in user.

    Connect with: ws://<host>/ws/notifications?token=<access_token>

    Every message is `{"event": ..., "data": {...}, "sent_at": ...}`:

    * `connected` — sent once on connect: `{user_id, role, unread_count}`
    * `notification` — a new notification (same fields as GET /notifications)
    * `order_status_updated` — `{order_id, order_number, order_status,
      previous_status, payment_status, ...}`; staff/admin receive it for
      every order, customers for their own
    * `cart_updated` — the full cart (`items`, `grand_total`, ...) plus `reason`
    * `notifications_read` — `{notification_ids, unread_count}`

    Send the text `ping` to get a `pong` back (keep-alive).
    """
    payload = decode_token(token, expected_type="access")
    if payload is None:
        await websocket.close(code=4401, reason="Invalid or expired token")
        return
    user_id = int(payload["sub"])
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            await websocket.close(code=4401, reason="User not found")
            return
        role, unread = user.role.value, _unread_count(db, user_id)
    finally:
        db.close()

    await manager.connect(user_id, role, websocket)
    try:
        await websocket.send_json(envelope("connected", {"user_id": user_id, "role": role, "unread_count": unread}))
        while True:
            text = await websocket.receive_text()
            if text.strip().lower() == "ping":
                await websocket.send_json(envelope("pong", {}))
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(user_id, websocket)
