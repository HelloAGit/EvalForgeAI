"""Background worker: scheduler ticks, queued evaluation runs and video jobs.

Run with ``python -m app.worker``. Safe to run as several processes (all claims are atomic).
"""
import logging
import signal
import threading
import time
import uuid

from app.config import settings
from app.database import SessionLocal

logger = logging.getLogger("evalforge.worker")


def run_once(worker_id: str = "worker", gateway=None, renderer=None, tts=None) -> int:
    """One pass over all work sources. Returns the number of units of work processed."""
    from app.services import evaluation_runner, scheduler, video_worker
    done = 0
    with SessionLocal() as db:
        scheduler.tick(db)
    with SessionLocal() as db:
        run = evaluation_runner.claim_pending_run(db)
        if run:
            evaluation_runner.execute_run(db, run, gateway)
            done += 1
    with SessionLocal() as db:
        done += video_worker.process_next(db, worker_id, gateway=gateway, renderer=renderer, tts=tts)
    return done


def run_forever(stop: threading.Event) -> None:
    worker_id = f"worker-{uuid.uuid4().hex[:8]}"
    logger.info("worker %s started", worker_id)
    while not stop.is_set():
        try:
            busy = run_once(worker_id)
        except Exception:
            logger.exception("worker iteration failed")
            busy = 0
        if not busy:
            stop.wait(settings.WORKER_POLL_SECONDS)
    logger.info("worker %s stopped", worker_id)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if settings.AUTO_MIGRATE:
        from app.migrations import upgrade_database
        upgrade_database()
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())  # graceful shutdown: finish the current unit, then exit
    run_forever(stop)


if __name__ == "__main__":
    main()
