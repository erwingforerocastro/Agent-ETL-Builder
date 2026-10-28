"""Thread-safe in-process cancellation token."""

import threading


class EventCancellationToken:
    """A process-local cancellation flag backed by ``threading.Event``."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


__all__ = ["EventCancellationToken"]
