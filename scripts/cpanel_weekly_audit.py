"""
Cron entrypoint for cPanel.

Runs the full audit and sends the report email without relying on the
Passenger web process staying alive. Use this from cPanel Cron Jobs.
"""
from __future__ import annotations

import fcntl
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.pipeline import run_full_audit


def main() -> int:
    reports_dir = PROJECT_ROOT / settings.REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)
    lock_path = reports_dir / ".weekly_audit.lock"

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [cron_audit] %(message)s")

    with lock_path.open("w") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.warning("Another audit is already running; skipping this cron execution.")
            return 0

        logging.info("Starting scheduled audit for %s", settings.SITE_BASE_URL)
        run_full_audit(send_email=True)
        logging.info("Scheduled audit completed.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
