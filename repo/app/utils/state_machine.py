from datetime import datetime, timezone
from app.extensions import db
from app.models.visit import Visit, VisitTransition

VALID_TRANSITIONS = {
    "booked": {"pending_payment", "checked_in", "canceled", "no_show"},
    "pending_payment": {"checked_in", "canceled"},
    "checked_in": {"seen", "canceled", "no_show"},
    "seen": set(),
    "canceled": set(),
    "no_show": set(),
}

TERMINAL_STATES = {"seen", "canceled", "no_show"}


def transition_visit(visit, to_status, changed_by_id, reason=None, request_token=None):
    """Transition a visit to a new status with optimistic concurrency control.

    Raises ValueError for invalid transitions.
    Returns the VisitTransition record on success.
    """
    if to_status not in Visit.VALID_STATUSES:
        raise ValueError(f"Invalid target status: {to_status}")

    from_status = visit.status

    if from_status in TERMINAL_STATES:
        raise ValueError(f"Cannot transition from terminal state: {from_status}")

    allowed = VALID_TRANSITIONS.get(from_status, set())
    if to_status not in allowed:
        raise ValueError(f"Invalid transition from '{from_status}' to '{to_status}'")

    # Check for duplicate request token
    if request_token:
        existing = VisitTransition.query.filter_by(request_token=request_token).first()
        if existing:
            return existing

    # Optimistic concurrency: re-check current state
    current = db.session.get(Visit, visit.id)
    if current.status != from_status:
        raise ValueError(f"Visit status changed concurrently (expected '{from_status}', got '{current.status}')")

    transition = VisitTransition(
        visit_id=visit.id,
        from_status=from_status,
        to_status=to_status,
        changed_by=changed_by_id,
        reason=reason,
        request_token=request_token,
    )
    db.session.add(transition)
    visit.status = to_status
    visit.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    return transition
