"""Unit tests for the background run scheduler."""

import threading

import pytest

from infrastructure.scheduling.thread_pool import ThreadPoolRunScheduler


def test_thread_pool_scheduler_runs_submitted_task() -> None:
    scheduler = ThreadPoolRunScheduler(max_workers=1)
    finished = threading.Event()

    scheduler.submit("run-1", finished.set)

    assert finished.wait(timeout=1)
    scheduler.shutdown()


def test_thread_pool_scheduler_rejects_invalid_worker_count() -> None:
    with pytest.raises(ValueError, match="max_workers"):
        ThreadPoolRunScheduler(max_workers=0)
