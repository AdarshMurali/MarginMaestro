"""Per-user rate limit on the action endpoints (MM-117): approve, manager
approve, respond, check SLA and simulate each start or resume an agent run
that can call the LLM, so they're capped per user per minute (429 beyond).

In-process sliding window: enough for the demo's single API instance. With
several Cloud Run instances each enforces its own window -- a shared store
(Memorystore/Firestore) would be the production step.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException

WINDOW_SECONDS = 60.0


class SlidingWindowLimiter:
    def __init__(self, clock=time.monotonic) -> None:  # type: ignore[no-untyped-def]
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int) -> None:
        """Record one hit for `key`; raise 429 if it exceeds `limit` per minute."""
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = int(WINDOW_SECONDS - (now - hits[0])) + 1
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded: {limit} actions per minute",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)


ACTION_LIMITER = SlidingWindowLimiter()
