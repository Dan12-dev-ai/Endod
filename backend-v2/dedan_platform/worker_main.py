"""
Standalone notification worker.

    python -m dedan_platform.worker_main            # run forever
    python -m dedan_platform.worker_main --once     # drain one batch and exit
    python -m dedan_platform.worker_main --reconcile # repair coverage, then exit

Exists because the in-process loop in `main_clinical`'s lifespan is the wrong
shape for some deployments. With several API replicas, each process runs its own
loop: delivery stays *correct* (claiming is an atomic conditional UPDATE, so no
job can be taken twice), but throughput scales with replica count and a rolling
deploy restarts every loop at once.

For those deployments, run this as its own process -- one replica, supervised by
systemd or a Kubernetes Deployment/CronJob -- and leave
`NOTIFICATION_WORKER_ENABLED` off in the API. Both paths share the same
`worker_loop`, so behaviour does not diverge between them.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from dedan_platform import worker
from dedan_platform.db import create_all

logger = logging.getLogger("dedan_platform.worker_main")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='{"timestamp":"%(asctime)s","level":"%(levelname)s",'
               '"logger":"%(name)s","message":"%(message)s"}',
    )


async def _run() -> int:
    stop = asyncio.Event()

    # Stop on SIGTERM/SIGINT so a rolling deploy drains rather than kills.
    loop = asyncio.get_running_loop()
    for signame in ("SIGINT", "SIGTERM"):
        try:
            loop.add_signal_handler(getattr(signal, signame), stop.set)
        except (NotImplementedError, AttributeError):
            # Not available on every platform (notably Windows); the default
            # KeyboardInterrupt handling still applies.
            pass

    await worker.worker_loop(stop)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DEDAN Health notification worker")
    parser.add_argument(
        "--once", action="store_true",
        help="Drain a single batch of due notifications and exit.",
    )
    parser.add_argument(
        "--reconcile", action="store_true",
        help="Repair reminder coverage and exit without delivering anything.",
    )
    args = parser.parse_args(argv)

    _configure_logging()
    create_all()

    if args.reconcile:
        result = worker.reconcile()
        logger.info("reconciliation_complete", extra=result)
        print(result)
        return 0

    if args.once:
        summary = worker.run_once(limit=worker.WORKER_BATCH_SIZE)
        logger.info("single_pass_complete", extra=summary)
        print(summary)
        return 0

    logger.info(
        "worker_main_start",
        extra={
            "poll_interval": worker.WORKER_POLL_INTERVAL,
            "batch_size": worker.WORKER_BATCH_SIZE,
            "reconcile_on_start": worker.WORKER_RECONCILE_ON_START,
        },
    )
    return asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover - operational entrypoint
    sys.exit(main())