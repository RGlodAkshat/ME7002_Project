from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Machine


class DatabaseMachineAdapter:
    def choose(self, db: Session, capability: str, exclude_id: int | None = None) -> Machine | None:
        machines = db.scalars(select(Machine).where(Machine.status == "available").order_by(Machine.id)).all()
        return next(
            (machine for machine in machines if capability in machine.capabilities and machine.id != exclude_id),
            None,
        )
