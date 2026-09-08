from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..deps import get_current_user
from ..models import Notification, User
from ..schemas import NotificationOut
from ..security import decode_token
from ..services.notification_service import manager

router = APIRouter(tags=["Notifications"])


@router.get("/notifications", response_model=List[NotificationOut])
def list_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    unread_only: bool = False,
):
    query = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))
    return query.order_by(Notification.created_at.desc()).limit(100).all()


@router.put("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
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


@router.put("/notifications/read-all")
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.is_read.is_(False))
        .update({Notification.is_read: True})
    )
    db.commit()
    return {"marked_read": updated}


@router.websocket("/ws/notifications")
async def notifications_ws(websocket: WebSocket, token: str = Query(...)):
    """Real-time notification stream.

    Connect with: ws://localhost:8000/ws/notifications?token=<access_token>
    Server pushes JSON payloads: {id, type, title, message, created_at}
    """
    payload = decode_token(token, expected_type="access")
    if payload is None:
        await websocket.close(code=4401, reason="Invalid or expired token")
        return
    user_id = int(payload["sub"])
    db = SessionLocal()
    try:
        if db.get(User, user_id) is None:
            await websocket.close(code=4401, reason="User not found")
            return
    finally:
        db.close()

    await manager.connect(user_id, websocket)
    try:
        while True:
            # Keep the connection alive; client messages are treated as pings.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
