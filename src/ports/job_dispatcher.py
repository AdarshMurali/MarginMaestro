from typing import Protocol


class DeskJobDispatcher(Protocol):
    """Arranges for a queued desk-chat job to actually run (MM-147
    follow-up). `dispatch` returns as soon as the job is handed off -- it
    may already be finished by the time it returns (SyncDeskJobDispatcher,
    local dev) or still be running (CloudTasksDeskJobDispatcher, GCP): the
    caller always re-reads the job row to see which."""

    def dispatch(self, job_id: str) -> None: ...
