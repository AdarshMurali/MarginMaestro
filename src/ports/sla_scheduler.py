from datetime import datetime
from typing import Protocol


class SlaScheduler(Protocol):
    """Arranges for a margin call's SLA check to run at its deadline (MM-122).

    The check itself is `POST /internal/sla/{thread_id}/check`, which resumes
    the paused run; this port only decides *when* it gets called."""

    def schedule_check(self, thread_id: str, at: datetime) -> None:
        """Schedule one check for `thread_id` at `at`. Calling it again for the
        same thread must not schedule a second check."""
        ...
