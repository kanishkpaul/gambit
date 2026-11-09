"""Every tunable number in gambit lives here: thresholds, budgets, noise models and allocations.

Sources are the research reports kept outside the repository (reports 02, 06, 07) and the bake-off
measurements in `bakeoff/RESULTS.md`. Change a number here, never inline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_ID = "dev.kanishkpaul.gambit"


def data_dir() -> Path:
    """Where the SQLite file lives. `GAMBIT_DATA_DIR` overrides (tests, dev sandboxes)."""
    override = os.environ.get("GAMBIT_DATA_DIR")
    base = Path(override) if override else Path.home() / "Library" / "Application Support" / APP_ID
    base.mkdir(parents=True, exist_ok=True)
    return base


# ── Move classification ──────────────────────────────────────────────────────────────────────────
# "Blunder" follows the research definition: a move that loses 2 pawns or more (report 02).
# Evaluations are clamped so that +9 → +7 in a won position isn't counted as an error, and a forced
# mate counts as a large but finite score.
EVAL_CLAMP_CP = 1000
MATE_CP = 1000
INACCURACY_CP = 50
MISTAKE_CP = 100
BLUNDER_CP = 200
# A move that still leaves the mover at least this far ahead is never flagged.
STILL_WINNING_CP = 300

# Time trouble: a move made with less than this share of the base time left on the clock.
TIME_TROUBLE_SHARE = 0.10


# ── Batch analysis (bakeoff/RESULTS.md §1) ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class EngineBudget:
    workers: int = 4  # one per performance core; efficiency cores add almost nothing
    threads: int = 1
    hash_mb: int = 64
    nodes: int = 100_000  # ~11 positions/s on 4 workers → ~4 h per 2,000 games
    deep_nodes: int = 1_000_000  # critical moments only (blunders) get re-searched
    pv_len: int = 8
    games_in_flight: int = 3  # overlap games so workers don't idle at game boundaries


BATCH = EngineBudget()
STOCKFISH_PATH = os.environ.get("GAMBIT_STOCKFISH", "stockfish")


# ── Rating noise (reports 02 and 07) ────────────────────────────────────────────────────────────
# Stationary SD of an online rating at fixed skill. Chess.com ≈ K 20 pool (±40); established Lichess
# Glicko-2 is quieter (±30). The shaded band is ±2 SD around the rolling mean: inside it is ordinary
# fluctuation.
NOISE_SD = {"chesscom": 40, "lichess": 30}
NOISE_BAND_SDS = 2
ROLLING_WINDOW = 50  # games; judge progress on rolling 50–100-game averages
# Ratings are a random walk, so a regression t-test overstates certainty. Instead a trend counts as
# real only when the rolling mean has moved more than the noise band over at least TREND_MIN_GAMES.
TREND_MIN_GAMES = 50
TREND_LOOKBACK = 100
# Gate 0: an ordinary adult improves ~+95 rating points a year (report 02).
ORDINARY_ADULT_PER_YEAR = 95
GATE0_DAYS = 182

# Phase division (a simplified version of Lichess's Divider): count of non-pawn, non-king pieces.
MIDDLEGAME_MAJORS_MINORS = 10
ENDGAME_MAJORS_MINORS = 6
OPENING_MAX_PLY = 30

# ── Mirror audit ────────────────────────────────────────────────────────────────────────────────
AUDIT_TIMEBOX_MIN = 45
AUDIT_SOFT_WARNING_MIN = 40
AUDIT_MAX_LESSONS = 3
AUDIT_MIN_OPENING_GAMES = 8

# ── Network ─────────────────────────────────────────────────────────────────────────────────────
# Chess.com asks for an identifying User-Agent; use a generic one (no personal contact details).
USER_AGENT = "gambit/0.1 (personal chess trainer)"
CHESSCOM_API = "https://api.chess.com/pub"
LICHESS_API = "https://lichess.org"
RATE_LIMIT_WAIT_S = 60  # Lichess asks for a full minute after a 429

# ── Stage allocations (docs/PLAN.md; starting point, untested) ──────────────────────────────────
STAGE_ALLOCATIONS = {
    1: {"solving": 35, "analysis": 20, "endgames": 15, "master_games": 5, "openings": 5, "play": 20},
    2: {"solving": 30, "analysis": 20, "endgames": 15, "master_games": 15, "openings": 5, "play": 15},
    3: {"solving": 25, "analysis": 20, "endgames": 15, "master_games": 15, "openings": 10, "play": 15},
    4: {"solving": 20, "analysis": 15, "endgames": 10, "master_games": 15, "openings": 20, "play": 20},
}

# Time classes we treat as "serious" for the Slope headline.
SERIOUS_TIME_CLASSES = ("rapid", "classical", "daily")
