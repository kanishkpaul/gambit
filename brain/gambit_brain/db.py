"""SQLite storage. The brain is the single writer; every connection is opened here.

Schema changes are append-only migrations keyed by `PRAGMA user_version`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from . import config

MIGRATIONS: list[str] = [
    # 1 · Mirror
    """
    CREATE TABLE settings (
      key   TEXT PRIMARY KEY,
      value TEXT NOT NULL            -- JSON
    );

    CREATE TABLE sync_state (
      platform TEXT NOT NULL,
      username TEXT NOT NULL,
      cursor   TEXT,                 -- chesscom: JSON {archive_url: etag}; lichess: last createdAt ms
      synced_at INTEGER,
      PRIMARY KEY (platform, username)
    );

    CREATE TABLE games (
      id           INTEGER PRIMARY KEY,
      platform     TEXT NOT NULL,    -- 'chesscom' | 'lichess'
      platform_id  TEXT NOT NULL,
      url          TEXT,
      played_at    INTEGER NOT NULL, -- unix seconds, game end
      time_class   TEXT NOT NULL,    -- bullet | blitz | rapid | classical | daily
      time_control TEXT,
      base_s       INTEGER,
      inc_s        INTEGER,
      rated        INTEGER NOT NULL,
      my_color     TEXT NOT NULL,    -- 'white' | 'black'
      my_rating    INTEGER,
      opp_rating   INTEGER,
      opp_name     TEXT,
      result       TEXT NOT NULL,    -- 'win' | 'loss' | 'draw'
      termination  TEXT,             -- normalised: checkmate, resign, timeout, ...
      eco          TEXT,
      opening      TEXT,
      ply_count    INTEGER NOT NULL,
      pgn          TEXT NOT NULL,
      analysed_at  INTEGER,          -- first pass done
      deep_at      INTEGER,          -- critical moments re-searched
      UNIQUE (platform, platform_id)
    );
    CREATE INDEX games_played ON games (played_at);
    CREATE INDEX games_pending ON games (analysed_at, played_at);

    CREATE TABLE moves (
      game_id        INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
      ply            INTEGER NOT NULL, -- 1-based half-move
      color          TEXT NOT NULL,
      san            TEXT NOT NULL,
      uci            TEXT NOT NULL,
      fen_before     TEXT NOT NULL,
      epd_before     TEXT NOT NULL,
      epd_after      TEXT NOT NULL,
      phase          TEXT NOT NULL,    -- opening | middlegame | endgame
      clock_ms       INTEGER,          -- clock after the move
      spent_ms       INTEGER,
      cp_loss        INTEGER,          -- mover's view, clamped
      wc_loss        REAL,             -- winning-chance drop, 0..1
      class          TEXT,             -- NULL until analysed; best | ok | inaccuracy | mistake | blunder
      motifs         TEXT,             -- JSON array
      time_trouble   INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (game_id, ply)
    );
    CREATE INDEX moves_class ON moves (class);

    -- Evaluations keyed by EPD (position without move counters), White's point of view.
    CREATE TABLE evals (
      epd        TEXT PRIMARY KEY,
      cp         INTEGER,
      mate       INTEGER,
      best_uci   TEXT,
      pv         TEXT,                 -- space-separated UCI
      nodes      INTEGER,
      source     TEXT NOT NULL,        -- 'lichess' | 'sf' | 'terminal'
      updated_at INTEGER NOT NULL
    );

    CREATE TABLE audit (
      id         INTEGER PRIMARY KEY CHECK (id = 1),  -- one-time: a single row, ever
      started_at INTEGER NOT NULL,
      report     TEXT NOT NULL,        -- JSON snapshot
      lessons    TEXT,                 -- JSON array of 1–3 strings
      filed_at   INTEGER
    );
    """,
    # 2 · Solve
    """
    -- Lichess puzzle library (CC0), filtered on import. FEN is before the opponent's lead-in move.
    CREATE TABLE puzzles (
      id         TEXT PRIMARY KEY,
      fen        TEXT NOT NULL,
      moves      TEXT NOT NULL,       -- space-separated UCI: lead-in, then solution
      rating     INTEGER NOT NULL,
      rd         INTEGER NOT NULL,
      popularity INTEGER NOT NULL,
      plays      INTEGER NOT NULL,
      themes     TEXT NOT NULL,       -- space-separated Lichess themes
      game_url   TEXT,
      opening    TEXT
    );
    CREATE INDEX puzzles_rating ON puzzles (rating);

    -- Everything you can be asked to solve: library puzzles and positions from your own games.
    CREATE TABLE items (
      id         INTEGER PRIMARY KEY,
      kind       TEXT NOT NULL,       -- 'puzzle' | 'own'
      ref        TEXT NOT NULL,       -- puzzle id, or 'game_id:ply' (+ ':m' for the colour-mirrored variant)
      fen        TEXT NOT NULL,       -- position before the lead-in move (or the solver's position if none)
      lead_uci   TEXT,                -- opponent's move shown before you solve
      solution   TEXT NOT NULL,       -- space-separated UCI; your moves at even indexes
      reveal     TEXT,                -- the full line shown after you answer, if longer than the solution
      themes     TEXT NOT NULL,       -- JSON array
      rating     INTEGER,
      created_at INTEGER NOT NULL,
      UNIQUE (kind, ref)
    );

    CREATE TABLE cards (
      item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
      card    TEXT NOT NULL,          -- py-fsrs Card JSON
      due     INTEGER NOT NULL
    );
    CREATE INDEX cards_due ON cards (due);

    CREATE TABLE solve_sessions (
      id          INTEGER PRIMARY KEY,
      mode        TEXT NOT NULL,      -- 'standard' | 'speed'
      started_at  INTEGER NOT NULL,
      ended_at    INTEGER,
      timebox_min INTEGER NOT NULL,
      planned     INTEGER NOT NULL
    );

    CREATE TABLE reviews (
      id           INTEGER PRIMARY KEY,
      item_id      INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
      session_id   INTEGER REFERENCES solve_sessions(id),
      at           INTEGER NOT NULL,
      mode         TEXT NOT NULL,
      first_seen   INTEGER NOT NULL,  -- 1 if this was the first attempt at the item
      correct      INTEGER NOT NULL,
      confidence   TEXT,              -- guess | unsure | sure
      answer       TEXT,              -- your moves, UCI
      line         TEXT,              -- the line you typed before committing
      ms           INTEGER,
      grade        INTEGER            -- FSRS rating 1–4, NULL in speed mode
    );
    CREATE INDEX reviews_item ON reviews (item_id);
    """,
    # 3 · Game Lab and guardrails
    """
    -- One post-mortem per game. The engine stays locked until you've logged your critical moments.
    CREATE TABLE lab_sessions (
      id          INTEGER PRIMARY KEY,
      game_id     INTEGER NOT NULL UNIQUE REFERENCES games(id) ON DELETE CASCADE,
      started_at  INTEGER NOT NULL,
      unlocked_at INTEGER,
      closed_at   INTEGER,
      notes       TEXT NOT NULL DEFAULT '{}',   -- JSON {ply: your comment}
      reveal      TEXT,                         -- JSON snapshot computed at unlock
      checks      TEXT NOT NULL DEFAULT '{}'    -- JSON {epd: engine checks}, for the reassurance limiter
    );

    CREATE TABLE lab_moments (
      session_id INTEGER NOT NULL REFERENCES lab_sessions(id) ON DELETE CASCADE,
      ply        INTEGER NOT NULL,
      note       TEXT NOT NULL,
      candidate  TEXT,                          -- the move you think was better (SAN, as typed)
      created_at INTEGER NOT NULL,
      PRIMARY KEY (session_id, ply)
    );

    CREATE TABLE lessons (
      id         INTEGER PRIMARY KEY,
      source     TEXT NOT NULL,                 -- 'lab'
      ref        TEXT,
      text       TEXT NOT NULL,
      created_at INTEGER NOT NULL
    );
    """,
    # 4 · Train: human-level fits
    """
    -- How human-like each side's moves were, per game: Maia log-likelihood totals at every level.
    -- Totals add across games, so pooled estimates (you, or a bot you keep playing) narrow honestly.
    CREATE TABLE maia_fits (
      game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
      side    TEXT NOT NULL,          -- 'me' | 'opp'
      moves   INTEGER NOT NULL,
      totals  TEXT NOT NULL,          -- JSON list, one per config.MAIA_LEVELS
      level   INTEGER,
      PRIMARY KEY (game_id, side)
    );
    """,
    # 5 · Deepen
    """
    -- Calibration: a fresh, difficulty-spread set solved cold and timed every 6–8 weeks.
    CREATE TABLE calibrations (
      id          INTEGER PRIMARY KEY,
      session_id  INTEGER REFERENCES solve_sessions(id),
      started_at  INTEGER NOT NULL,
      finished_at INTEGER,
      attempted   INTEGER,
      solved      INTEGER,
      performance INTEGER,               -- performance rating on the Lichess puzzle scale
      mean_rating INTEGER                -- average puzzle rating of the set
    );

    CREATE TABLE calc_attempts (
      id            INTEGER PRIMARY KEY,
      at            INTEGER NOT NULL,
      puzzle_id     TEXT NOT NULL,
      mode          TEXT NOT NULL,       -- 'board' | 'visual'
      candidates    TEXT,                -- JSON list of SAN
      line          TEXT,                -- your main line, SAN
      scan_note     TEXT,
      first_correct INTEGER NOT NULL,
      saw_it        INTEGER NOT NULL,    -- the right first move was among your candidates
      plies_matched INTEGER NOT NULL,
      line_len      INTEGER NOT NULL,
      ms            INTEGER,
      end_cp        INTEGER,             -- engine eval at the end of your line, your point of view
      best_cp       INTEGER
    );
    CREATE INDEX calc_puzzle ON calc_attempts (puzzle_id);

    -- Your repertoire: one move per position where it's your turn, built from your games or pinned.
    CREATE TABLE repertoire (
      color  TEXT NOT NULL,
      epd    TEXT NOT NULL,
      fen    TEXT NOT NULL,
      uci    TEXT NOT NULL,
      san    TEXT NOT NULL,
      source TEXT NOT NULL,              -- 'games' | 'pinned'
      games  INTEGER NOT NULL DEFAULT 0,
      ply    INTEGER NOT NULL,
      PRIMARY KEY (color, epd)
    );

    CREATE TABLE master_games (
      id        INTEGER PRIMARY KEY,
      source_id TEXT NOT NULL UNIQUE,    -- broadcast game URL or a hash
      event     TEXT,
      white     TEXT, black TEXT,
      white_elo INTEGER, black_elo INTEGER,
      date      TEXT,
      result    TEXT NOT NULL,
      eco       TEXT, opening TEXT,
      pgn       TEXT NOT NULL,
      ply_count INTEGER NOT NULL
    );
    -- Opening positions of master games, for matching your repertoire's structures.
    CREATE TABLE master_positions (
      epd     TEXT NOT NULL,
      game_id INTEGER NOT NULL REFERENCES master_games(id) ON DELETE CASCADE,
      ply     INTEGER NOT NULL,
      PRIMARY KEY (epd, game_id)
    );

    CREATE TABLE guess_sessions (
      id          INTEGER PRIMARY KEY,
      game_id     INTEGER NOT NULL REFERENCES master_games(id),
      side        TEXT NOT NULL,
      start_ply   INTEGER NOT NULL,
      started_at  INTEGER NOT NULL,
      finished_at INTEGER,
      guesses     INTEGER NOT NULL DEFAULT 0,
      matched     INTEGER NOT NULL DEFAULT 0,
      as_good     INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE coach_reports (
      id         INTEGER PRIMARY KEY,
      kind       TEXT NOT NULL,          -- 'weekly' | 'explain'
      created_at INTEGER NOT NULL,
      model      TEXT NOT NULL,
      input      TEXT NOT NULL,          -- JSON: exactly what the model was given
      output     TEXT NOT NULL           -- JSON: what it returned, after grounding checks
    );
    """,
]


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or config.data_dir() / "gambit.sqlite"
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
        with tx(conn):
            _exec_script(conn, sql)
            conn.execute(f"PRAGMA user_version = {i}")


def _exec_script(conn: sqlite3.Connection, sql: str) -> None:
    # executescript() commits implicitly; run statements one by one so the migration stays atomic.
    # Strip `--` comments first: they may contain semicolons.
    sql = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    for stmt in sql.split(";"):
        if stmt.strip():
            conn.execute(stmt)


class tx:
    """`with tx(conn):` — one explicit transaction (the connection runs in autocommit mode)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN")
        return self.conn

    def __exit__(self, exc_type, *_):
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        return False


def get_setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )


def all_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    return {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT key, value FROM settings")}
