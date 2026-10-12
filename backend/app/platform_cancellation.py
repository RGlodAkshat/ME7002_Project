"""Cancellation preserves history and holds equipment until a safe stop."""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .platform_models import Order, OrderCancellation, Review, Task, User, now

PENDING = "Order cancellation requested. Stop the physical operation safely and contact the administrator to confirm the stop. Do not resume work."


def details(db: Session, order: Order) -> dict | None:
    item = db.get(OrderCancellation, order.id)
    return {"reason": item.reason, "requested_by": item.requested_by, "requested_at": item.requested_at.isoformat(), "physical_stops": item.physical_stops} if item else None


def request(db: Session, order: Order, actor: User, reason: str) -> None:
    if order.status == "completed":
        raise HTTPException(409, "Completed orders cannot be cancelled")
    if order.status in {"cancelled", "cancelling"}:
        return
    db.add(OrderCancellation(order_id=order.id, requested_by=actor.id, reason=reason))
    order.status = "cancelling"
    db.flush()
    reconcile(db)


def reconcile(db: Session) -> None:
    from .platform_service import release, stop_task
    from .platform_telemetry import observed
    for order in db.query(Order).filter(Order.status == "cancelling").all():
        held = False
        for task in db.query(Task).filter(Task.order_id == order.id).all():
            if task.status in {"completed", "cancelled"}:
                continue
            for review in db.query(Review).filter_by(task_id=task.id, status="pending").all():
                review.status = "cancelled"
            # A database observation is not a remote stop acknowledgement—even
            # a complete signal history cannot certify that the equipment is safe.
            needs_stop = task.kind == "machine" and task.command_id and task.machine_id
            if needs_stop and (observed(db, task) or not stop_task(db, task)):
                task.status = "paused"
                task.dispatch_error = PENDING
                held = True
            else:
                release(task)
                task.status = "cancelled"
                task.dispatch_error = None
        if not held:
            order.status = "cancelled"
    db.flush()


def confirm(db: Session, task: Task, actor: User) -> None:
    from .platform_service import release
    item = db.get(OrderCancellation, task.order_id)
    if not item:
        raise HTTPException(409, "No cancellation is awaiting a physical stop")
    stops = dict(item.physical_stops or {})
    stops[task.id] = {"actor": actor.id, "confirmed_at": now().isoformat()}
    item.physical_stops = stops
    release(task)
    task.status = "cancelled"
    task.dispatch_error = None
    db.flush()
    reconcile(db)
