#!/bin/bash
set -e
mkdir -p 'src'
cat > 'src/scheduler.py' <<'PE_EOF_1'
"""Background job scheduler.

This module owns the in-process job queue, worker pool bookkeeping and the
retry policy used by all asynchronous tasks (report generation, mail
delivery, cache warming, ...).  It intentionally has no external
dependencies so that it can be imported from the CLI, the web app and the
test-suite without pulling in the whole framework.
"""

from __future__ import annotations

import heapq
import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("scheduler")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

#: Default number of worker threads when the caller does not specify one.
DEFAULT_WORKERS = 4

#: How long (seconds) a worker waits on the queue before re-checking the
#: shutdown flag.
POLL_INTERVAL = 0.25

#: Maximum number of jobs that may sit in the queue before `submit` starts
#: rejecting new work.
QUEUE_HARD_LIMIT = 10_000

#: Soft limit at which we start logging warnings about queue depth.
QUEUE_SOFT_LIMIT = 2_500

#: Jobs that have been running longer than this are considered stuck and
#: are reported by `Scheduler.stuck_jobs()`.
STUCK_THRESHOLD_SECONDS = 900

#: How many times a job is retried after its first failure.
DEFAULT_MAX_RETRIES = 5

#: Multiplier used by the exponential back-off between retries.
RETRY_BACKOFF_BASE = 1.5

#: Hard upper bound for a single back-off sleep.
MAX_BACKOFF_SECONDS = 60.0

#: Initial delay (seconds) before the very first retry.
RETRY_INITIAL_DELAY = 0.5

#: Jitter applied to back-off values to avoid thundering herds, as a
#: fraction of the computed delay.
RETRY_JITTER_FRACTION = 0.1


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY_WAIT = "retry_wait"


class SchedulerError(RuntimeError):
    """Base class for all scheduler errors."""


class QueueFull(SchedulerError):
    """Raised by `submit` when the queue is at its hard limit."""


class JobNotFound(SchedulerError):
    """Raised when a job id is unknown to the scheduler."""


@dataclass(order=True)
class _QueueEntry:
    run_at: float
    seq: int
    job_id: str = field(compare=False)


@dataclass
class Job:
    id: str
    name: str
    func: Callable[..., Any]
    args: Tuple[Any, ...] = ()
    kwargs: Dict[str, Any] = field(default_factory=dict)
    max_retries: int = DEFAULT_MAX_RETRIES
    attempts: int = 0
    state: JobState = JobState.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    last_error: Optional[str] = None
    result: Any = None
    tags: List[str] = field(default_factory=list)

    @property
    def duration(self) -> Optional[float]:
        if self.started_at is None:
            return None
        end = self.finished_at or time.time()
        return end - self.started_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state.value,
            "attempts": self.attempts,
            "max_retries": self.max_retries,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "last_error": self.last_error,
            "tags": list(self.tags),
        }


class _Stats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: Dict[str, int] = defaultdict(int)
        self.timings: Dict[str, List[float]] = defaultdict(list)

    def incr(self, key: str, n: int = 1) -> None:
        with self._lock:
            self.counters[key] += n

    def record(self, key: str, seconds: float) -> None:
        with self._lock:
            bucket = self.timings[key]
            bucket.append(seconds)
            if len(bucket) > 1000:
                del bucket[: len(bucket) - 1000]

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            out: Dict[str, Any] = {"counters": dict(self.counters), "timings": {}}
            for key, values in self.timings.items():
                if not values:
                    continue
                ordered = sorted(values)
                out["timings"][key] = {
                    "count": len(ordered),
                    "p50": ordered[len(ordered) // 2],
                    "p95": ordered[int(len(ordered) * 0.95) - 1] if len(ordered) >= 20 else ordered[-1],
                    "max": ordered[-1],
                }
            return out


class Scheduler:
    """Thread-pool based job scheduler with delayed execution and retries."""

    def __init__(self, workers: int = DEFAULT_WORKERS, name: str = "default") -> None:
        if workers < 1:
            raise ValueError("workers must be >= 1")
        self.name = name
        self._workers_wanted = workers
        self._threads: List[threading.Thread] = []
        self._cv = threading.Condition()
        self._heap: List[_QueueEntry] = []
        self._seq = 0
        self._jobs: Dict[str, Job] = {}
        self._shutdown = False
        self._stats = _Stats()
        self._hooks: Dict[str, List[Callable[[Job], None]]] = defaultdict(list)

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        with self._cv:
            if self._threads:
                return
            self._shutdown = False
            for i in range(self._workers_wanted):
                t = threading.Thread(
                    target=self._worker_loop,
                    name=f"{self.name}-worker-{i}",
                    daemon=True,
                )
                t.start()
                self._threads.append(t)
        log.info("scheduler %s started with %d workers", self.name, self._workers_wanted)

    def shutdown(self, wait: bool = True, timeout: Optional[float] = None) -> None:
        with self._cv:
            self._shutdown = True
            self._cv.notify_all()
        if wait:
            deadline = None if timeout is None else time.time() + timeout
            for t in self._threads:
                remaining = None if deadline is None else max(0.0, deadline - time.time())
                t.join(remaining)
        self._threads.clear()
        log.info("scheduler %s stopped", self.name)

    # -- hooks -------------------------------------------------------------

    def on(self, event: str, callback: Callable[[Job], None]) -> None:
        if event not in ("submitted", "started", "succeeded", "failed", "retry", "cancelled"):
            raise ValueError(f"unknown event {event!r}")
        self._hooks[event].append(callback)

    def _emit(self, event: str, job: Job) -> None:
        for cb in self._hooks.get(event, ()):
            try:
                cb(job)
            except Exception:  # noqa: BLE001
                log.exception("hook for %s raised", event)

    # -- submission --------------------------------------------------------

    def submit(
        self,
        func: Callable[..., Any],
        *args: Any,
        name: Optional[str] = None,
        delay: float = 0.0,
        max_retries: int = DEFAULT_MAX_RETRIES,
        tags: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> str:
        job = Job(
            id=uuid.uuid4().hex,
            name=name or getattr(func, "__name__", "job"),
            func=func,
            args=args,
            kwargs=kwargs,
            max_retries=max_retries,
            tags=list(tags or []),
        )
        with self._cv:
            depth = len(self._heap)
            if depth >= QUEUE_HARD_LIMIT:
                self._stats.incr("rejected")
                raise QueueFull(f"queue depth {depth} >= {QUEUE_HARD_LIMIT}")
            if depth >= QUEUE_SOFT_LIMIT:
                log.warning("queue depth %d exceeds soft limit", depth)
            self._jobs[job.id] = job
            self._push(job.id, time.time() + max(0.0, delay))
        self._stats.incr("submitted")
        self._emit("submitted", job)
        return job.id

    def _push(self, job_id: str, run_at: float) -> None:
        # caller must hold self._cv
        self._seq += 1
        heapq.heappush(self._heap, _QueueEntry(run_at, self._seq, job_id))
        self._cv.notify()

    def cancel(self, job_id: str) -> bool:
        with self._cv:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFound(job_id)
            if job.state not in (JobState.PENDING, JobState.RETRY_WAIT):
                return False
            job.state = JobState.CANCELLED
            job.finished_at = time.time()
            self._heap = [e for e in self._heap if e.job_id != job_id]
            heapq.heapify(self._heap)
        self._stats.incr("cancelled")
        self._emit("cancelled", job)
        return True

    # -- inspection --------------------------------------------------------

    def get(self, job_id: str) -> Job:
        with self._cv:
            job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        return job

    def list_jobs(self, state: Optional[JobState] = None, tag: Optional[str] = None) -> List[Job]:
        with self._cv:
            jobs = list(self._jobs.values())
        if state is not None:
            jobs = [j for j in jobs if j.state == state]
        if tag is not None:
            jobs = [j for j in jobs if tag in j.tags]
        return sorted(jobs, key=lambda j: j.created_at)

    def stuck_jobs(self) -> List[Job]:
        now = time.time()
        return [
            j
            for j in self.list_jobs(state=JobState.RUNNING)
            if j.started_at is not None and now - j.started_at > STUCK_THRESHOLD_SECONDS
        ]

    def stats(self) -> Dict[str, Any]:
        snap = self._stats.snapshot()
        with self._cv:
            snap["queue_depth"] = len(self._heap)
            snap["workers"] = len(self._threads)
        return snap

    def purge_finished(self, older_than: float = 3600.0) -> int:
        cutoff = time.time() - older_than
        removed = 0
        with self._cv:
            for job_id in list(self._jobs):
                job = self._jobs[job_id]
                if job.finished_at is not None and job.finished_at < cutoff:
                    del self._jobs[job_id]
                    removed += 1
        return removed

    # -- retry policy ------------------------------------------------------

    def _compute_backoff(self, attempt: int) -> float:
        """Return the delay before retry number ``attempt`` (1-based)."""
        if attempt < 1:
            return 0.0
        delay = RETRY_INITIAL_DELAY * (RETRY_BACKOFF_BASE ** (attempt - 1))
        delay = min(delay, MAX_BACKOFF_SECONDS)
        # Deterministic jitter derived from the attempt number so that unit
        # tests stay reproducible without patching `random`.
        jitter = ((attempt * 7919) % 100) / 100.0 * RETRY_JITTER_FRACTION * delay
        return delay + jitter

    def _should_retry(self, job: Job, exc: BaseException) -> bool:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            return False
        if getattr(exc, "no_retry", False):
            return False
        return job.attempts <= job.max_retries

    # -- worker loop -------------------------------------------------------

    def _next_ready(self) -> Optional[Job]:
        # caller must hold self._cv
        while self._heap:
            entry = self._heap[0]
            now = time.time()
            if entry.run_at > now:
                self._cv.wait(min(POLL_INTERVAL, entry.run_at - now))
                if self._shutdown:
                    return None
                continue
            heapq.heappop(self._heap)
            job = self._jobs.get(entry.job_id)
            if job is None or job.state == JobState.CANCELLED:
                continue
            return job
        return None

    def _worker_loop(self) -> None:
        while True:
            with self._cv:
                if self._shutdown:
                    return
                job = self._next_ready()
                if job is None:
                    self._cv.wait(POLL_INTERVAL)
                    continue
                job.state = JobState.RUNNING
                job.started_at = time.time()
                job.attempts += 1
            self._run_one(job)

    def _run_one(self, job: Job) -> None:
        self._emit("started", job)
        t0 = time.time()
        try:
            job.result = job.func(*job.args, **job.kwargs)
        except BaseException as exc:  # noqa: BLE001
            job.last_error = f"{type(exc).__name__}: {exc}"
            self._stats.record("job_seconds", time.time() - t0)
            if self._should_retry(job, exc):
                delay = self._compute_backoff(job.attempts)
                with self._cv:
                    job.state = JobState.RETRY_WAIT
                    self._push(job.id, time.time() + delay)
                self._stats.incr("retried")
                log.warning("job %s (%s) failed, retry in %.2fs: %s", job.id, job.name, delay, job.last_error)
                self._emit("retry", job)
                return
            job.state = JobState.FAILED
            job.finished_at = time.time()
            self._stats.incr("failed")
            log.error("job %s (%s) failed permanently: %s", job.id, job.name, job.last_error)
            self._emit("failed", job)
            return
        job.state = JobState.SUCCEEDED
        job.finished_at = time.time()
        self._stats.record("job_seconds", job.finished_at - t0)
        self._stats.incr("succeeded")
        self._emit("succeeded", job)


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------

_default: Optional[Scheduler] = None
_default_lock = threading.Lock()


def default_scheduler() -> Scheduler:
    global _default
    with _default_lock:
        if _default is None:
            _default = Scheduler()
            _default.start()
        return _default


def submit(func: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    return default_scheduler().submit(func, *args, **kwargs)


def wait_for(job_id: str, timeout: Optional[float] = None, poll: float = 0.05) -> Job:
    sched = default_scheduler()
    deadline = None if timeout is None else time.time() + timeout
    while True:
        job = sched.get(job_id)
        if job.state in (JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED):
            return job
        if deadline is not None and time.time() >= deadline:
            raise TimeoutError(f"job {job_id} still {job.state.value} after {timeout}s")
        time.sleep(poll)
PE_EOF_1
