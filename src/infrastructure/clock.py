"""System clock adapter."""

import time
from datetime import UTC, datetime


class SystemClock:
    """UTC wall clock plus monotonic sleep primitives."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


__all__ = ["SystemClock"]
