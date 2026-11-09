"""Calibration status: when the next cold, timed test is due, and how past tests went.

The test itself runs through Solve (mode 'calibration'): a fresh set spread around your solve
rating, one attempt each, timed, no hints, nothing revealed until the end, nothing scheduled.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from . import config

DAY = 86_400


def status(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = [dict(r) for r in conn.execute(
        "SELECT finished_at, attempted, solved, performance, mean_rating FROM calibrations "
        "WHERE finished_at IS NOT NULL ORDER BY finished_at")]
    last = rows[-1] if rows else None
    next_due = last["finished_at"] + config.CALIBRATION_EVERY_DAYS * DAY if last else None
    library = conn.execute("SELECT COUNT(*) FROM puzzles").fetchone()[0]
    return {
        "history": rows, "last": last, "due": next_due is None or time.time() >= next_due,
        "next_due_at": next_due, "every_days": config.CALIBRATION_EVERY_DAYS, "size": config.CALIBRATION_SIZE,
        "seconds": config.CALIBRATION_SECONDS, "spread": config.CALIBRATION_SPREAD, "library_ready": library > 0,
    }
