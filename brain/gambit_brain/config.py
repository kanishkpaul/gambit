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


# ── Solve (v0.2) ────────────────────────────────────────────────────────────────────────────────
# Lichess puzzle library: keep well-rated, popular, stable puzzles only.
PUZZLE_DB_URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
PUZZLE_MIN_POPULARITY = 90  # with 1,000+ plays: ~1.5M of ~5.9M puzzles, ~250 MB
PUZZLE_MIN_PLAYS = 1000
PUZZLE_MAX_RD = 90

SOLVE_SET_SIZE = 20
SOLVE_MAX_DUE = 12  # reviews first, but leave room for new material
SOLVE_MAX_NEW_OWN = 6  # positions from your games per set
SOLVE_TIMEBOX_MIN = 30
SOLVE_SOFT_WARNING_MIN = 25
SPEED_TIMEBOX_MIN = 5
SPEED_RATING_OFFSET = -300  # speed mode drills recognition on easier positions

# Starting solve rating on the Lichess puzzle scale. A 400–1200 Chess.com rapid player usually
# solves around 1100–1500 there; start in the middle and let results move it.
SOLVE_START_RATING = 1200
SOLVE_TARGET_OFFSET = -100  # aim slightly below your level: retrieval should mostly succeed
SOLVE_RATING_WINDOW = 75
SOLVE_K_EARLY, SOLVE_K, SOLVE_K_EARLY_N = 32, 16, 30

# FSRS. Learning steps are spaced so a failed position never returns within the same few minutes.
FSRS_DESIRED_RETENTION = 0.9
FSRS_LEARNING_STEPS_MIN = (10,)
FSRS_RELEARNING_STEPS_MIN = (10,)
FAST_SOLVE_MS = 20_000  # a sure, correct answer faster than this is graded Easy

# Own positions: accept any move within this many centipawns of the best one (checked live).
OWN_ACCEPT_CP = 50
OWN_MIN_EVAL_BEFORE = -200  # skip positions that were already lost before the blunder
LIVE = EngineBudget(workers=1, threads=3, hash_mb=128, nodes=400_000)

# Stage-1 theme weights (the error tail: hung pieces, simple tactics, threats you must see).
# Your own blunder motifs add weight to the matching themes.
THEME_WEIGHTS = {
    "hangingPiece": 3, "fork": 3, "pin": 2, "defensiveMove": 2, "mateIn1": 2, "mateIn2": 2,
    "skewer": 1.5, "discoveredAttack": 1.5, "backRankMate": 1.5, "trappedPiece": 1,
    "capturingDefender": 1, "deflection": 1, "attraction": 1, "doubleCheck": 0.5, "intermezzo": 0.5,
}
MOTIF_THEMES = {
    "hung_piece": ["hangingPiece"], "fork": ["fork"], "pin": ["pin", "skewer"],
    "discovered_attack": ["discoveredAttack"], "back_rank": ["backRankMate"],
    "allowed_mate": ["defensiveMove", "mateIn2"], "missed_mate": ["mateIn1", "mateIn2"],
    "missed_capture": ["hangingPiece", "capturingDefender"], "lost_material": ["deflection", "attraction"],
}
MOTIF_BOOST = 4.0  # added to a theme's weight in proportion to the share of your blunders it explains


# ── Game Lab and Maia (v0.3) ────────────────────────────────────────────────────────────────────
MAIA_ANALYSIS_MODEL = "maia3-23m"  # 23M: fast on CPU and validated at 57% move match
MAIA_SPARRING_MODEL = "maia3-79m"
MAIA_LEVELS = range(600, 2601, 100)  # a fit on either end means 'beyond the scale', never a number
MAIA_BATCH = 256
MAIA_MIN_MOVES = 12  # fewer moves than this and the band fit is noise
MAIA_LL_INTERVAL = 2.0  # log-likelihood drop that bounds the "likely range" of a band fit
MAIA_HIGHER_BY = 400  # "a stronger player": your level plus this
DEFAULT_PLAYING_ELO = 1000  # until a rated game tells us otherwise (Chess.com rapid 400–1200 start)

LAB_TIMEBOX_MIN = 45
LAB_SOFT_WARNING_MIN = 40
LAB_MAX_MOMENTS = 3
LAB_MAX_LESSONS = 3
LAB_ENGINE_NODES = 300_000  # positions the batch pass hasn't covered, analysed when you unlock
LAB_CRITICAL_MOMENTS = 3  # the engine's biggest swings among your moves
ENGINE_CHECK_NUDGE = 3  # repeated engine checks of one position before the reassurance nudge

# ── Guardrails ──────────────────────────────────────────────────────────────────────────────────
LICHESS_STATUS_POLL_S = 30  # live-game detection for the fair-play lock
STOP_LOSS_CAUTION = 2  # straight losses today
STOP_LOSS_STOP = 3


# ── Train (v0.4) ────────────────────────────────────────────────────────────────────────────────
TABLEBASE_URL = "https://tablebase.lichess.org/standard"
ENDGAME_HOLD_MOVES = 12  # survive this many of your moves with the draw intact
ENDGAME_DEFAULT_MOVES = 20

# Human-level labels. Maia-3 learned from Lichess blitz, so its levels are on that scale. The
# research found no trustworthy conversion to Chess.com at beginner-to-club level, so gambit measures
# your own: your rating against the Maia level your moves resemble, over your recent games.
MAIA_SCALE = "Lichess blitz"
PERSONAL_SCALE_GAMES = 40  # recent rated games pooled for your personal conversion
PERSONAL_SCALE_MIN_GAMES = 15
SPARRING_OFFSET = 100  # spar slightly above your level
SPARRING_TEMPERATURE = 1.0  # sample Maia's policy as-is: humans don't always play their top choice
SPARRING_TIME_CONTROLS = [(15, 10), (30, 0), (45, 15), (60, 30)]  # minutes + seconds; long games only
AUTO_IMPORT_MIN = 30  # fetch new games in the background this often (and right after a Lichess game ends)
PLANNER_WEEKLY_HOURS = 20  # 20–40 h/week is the plan; start at the low end
PLANNER_REST_DAYS = [6]  # Sunday (Monday = 0)
# Stage boundaries on your headline pool's rolling rating. Chess.com rapid follows report 02's stages
# (≤1500–1650 → 2000 → 2200); the Lichess column is an approximate +150–250 shift (report 07) and
# can be overridden in Settings.
STAGE_THRESHOLDS = {"chesscom": (1600, 2000, 2200), "lichess": (1800, 2150, 2350)}
