from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Operator, Task


class LeastLoadedQualifiedAssignment:
    """Stable deterministic assignment: least active work, then lowest operator id."""

    def choose(self, db: Session, task: Task) -> Operator | None:
        active = ("assigned", "in_progress", "awaiting_verification", "awaiting_manual_review")
        candidates = db.scalars(select(Operator).where(Operator.available.is_(True)).order_by(Operator.id)).all()
        qualified = [operator for operator in candidates if task.required_skill in operator.skills]
        if not qualified:
            return None
        loads = dict(
            db.execute(
                select(Task.assigned_operator_id, func.count(Task.id))
                .where(Task.status.in_(active), Task.assigned_operator_id.is_not(None))
                .group_by(Task.assigned_operator_id)
            ).all()
        )
        return min(qualified, key=lambda operator: (loads.get(operator.id, 0), operator.id))
