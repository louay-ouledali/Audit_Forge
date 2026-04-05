"""Forge Sentinel — notification bell API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.core.auth import get_current_user
from backend.database import get_db
from backend.models.notification import Notification
from backend.models.user import User
from backend.utils.datetime_utils import utc_iso

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Current user's notifications — unread first, newest first."""
    q = (
        db.query(Notification)
        .filter((Notification.user_id == current_user.id) | (Notification.user_id.is_(None)))
        .order_by(Notification.is_read.asc(), Notification.created_at.desc())
    )
    total = q.count()
    items = q.offset(skip).limit(limit).all()
    return {
        "total": total,
        "data": [
            {
                "id": n.id,
                "title": n.title,
                "body": n.body,
                "type": n.type,
                "icon": n.icon,
                "mission_id": n.mission_id,
                "entity_type": n.entity_type,
                "entity_id": n.entity_id,
                "link": n.link,
                "is_read": n.is_read,
                "created_at": utc_iso(n.created_at),
            }
            for n in items
        ],
    }


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    count = (
        db.query(Notification)
        .filter(
            (Notification.user_id == current_user.id) | (Notification.user_id.is_(None)),
            Notification.is_read == False,
        )
        .count()
    )
    return {"count": count}


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    n = db.query(Notification).filter(Notification.id == notification_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    # Authorization: only the owner (or broadcast) can mark as read
    if n.user_id is not None and n.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your notification")
    n.is_read = True
    db.commit()
    return {"message": "Marked as read"}


@router.post("/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Only mark this user's own notifications (skip broadcasts to avoid shared-state corruption)
    db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read.is_(False),
    ).update({"is_read": True}, synchronize_session="fetch")
    db.commit()
    return {"message": "All marked as read"}


@router.delete("/{notification_id}")
def dismiss_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    n = db.query(Notification).filter(Notification.id == notification_id).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    # Authorization: only the owner can dismiss
    if n.user_id is not None and n.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your notification")
    db.delete(n)
    db.commit()
    return {"message": "Dismissed"}
