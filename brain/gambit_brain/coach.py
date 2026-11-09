"""The coach: a weekly review of your metrics and plain-language explanations of engine lines.

It runs on a local model through Ollama (free, on this Mac, nothing leaves it). Which model is a
setting (`coach_model`), chosen from the ones installed in Ollama.

Grounded by construction:
- The weekly review sees only a facts object computed here, and every number it writes must be one
  of those facts; observations that cite anything else are removed before you see them.
- Explanations see only Stockfish's lines for the position (SAN, with evaluations). Every move it
  names and every evaluation it quotes must appear in those lines, or the point is removed.
Everything sent and returned is stored in coach_reports, so any statement can be traced back.
The coach is off under the fair-play lock and needs Ollama running with the chosen model installed.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Awaitable, Callable
from typing import Any

import chess
import httpx

from . import calibration, config, metrics, planner
from .chesslib import Eval
from .db import get_setting, tx

MultiAnalyse = Callable[[str, int, int], Awaitable[list[tuple[Eval, list[str]]]]]

ACTIVITIES = ("solving", "analysis", "endgames", "master_games", "openings", "play")
SAN_TOKEN = re.compile(
    r"\b(?:O-O(?:-O)?|[KQRBN][a-h]?[1-8]?x?[a-h][1-8]|[a-h]x[a-h][1-8](?:=[QRBN])?|[a-h][1-8](?:=[QRBN])?)[+#]?"
)
NUMBER = re.compile(r"(?<![\w.])[+−-]?\d+(?:[.,]\d+)?%?")
EVAL = re.compile(r"[+−-]\d+\.\d+")


class CoachError(ValueError):
    pass


WEEKLY_SYSTEM = """You are the weekly coach inside gambit, a private chess training app for one adult improver.

Ground rules:
- You are given a JSON object of facts. Use only those facts. Every number you write must appear in
  the facts exactly as given (you may write a percentage for a share given as a fraction, e.g. 0.34 as 34%).
  Never estimate, extrapolate or invent a number, a rating, a move or an evaluation.
- Ratings are noisy: a change inside the noise band is not a trend. Say so when it applies.
- Recommend a split of next week's training time across exactly these activities, as whole percentages
  that sum to 100: solving, analysis, endgames, master_games, openings, play. Start from the stage
  allocation in the facts and move at most 10 points in total, only where a fact supports it.
- The method: shrink the error tail (blunders per game), retrieval over re-reading, study over play.
- Tone: plain, specific, kind. No streaks, no scores out of ten, no motivational slogans, no shaming.
- Each observation must list the fact keys it relies on in `evidence`.
- Answer with a single JSON object matching the requested schema."""

EXPLAIN_SYSTEM = """You explain chess positions inside gambit for an adult improver rated around the
level given. You are given the position (FEN), the move the player chose, and Stockfish's top lines
with evaluations in pawns from the side to move's point of view.

Ground rules:
- Mention only moves that appear in the provided lines, written exactly as given (SAN).
- Quote an evaluation only if it appears in the provided lines, exactly as given.
- Explain ideas in plain words: what the best line threatens or prevents, what the chosen move allowed.
- Never claim anything about the position that the lines don't support; if unsure, say less.
- At most four short points.
- Answer with a single JSON object matching the requested schema."""

WEEKLY_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}}},
                "required": ["text", "evidence"],
                "additionalProperties": False,
            },
        },
        "next_week": {
            "type": "object",
            "properties": {a: {"type": "integer"} for a in ACTIVITIES},
            "required": list(ACTIVITIES),
            "additionalProperties": False,
        },
        "focus": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "observations", "next_week", "focus"],
    "additionalProperties": False,
}

EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}, "points": {"type": "array", "items": {"type": "string"}}},
    "required": ["summary", "points"],
    "additionalProperties": False,
}


# ── Facts ────────────────────────────────────────────────────────────────────────────────────────


def weekly_facts(conn: sqlite3.Connection, now: float | None = None) -> dict[str, Any]:
    now = now or time.time()
    since = int(now - 7 * 86_400)
    s = metrics.slope(conn)
    facts: dict[str, Any] = {"period_days": 7}
    if s.get("pool"):
        rating = s.get("rating") or []
        errors = s.get("errors") or []
        facts["pool"] = f"{s['pool']['platform']} {s['pool']['time_class']}"
        if rating:
            facts["rating_rolling_mean"] = round(rating[-1]["mean"])
            facts["rated_games_total"] = len(rating)
        facts["noise_band_points"] = s["noise"]["band"]
        if s.get("trend"):
            facts["trend_points_per_100_games"] = s["trend"]["per_100"]
            facts["trend_beyond_noise"] = s["trend"]["real"]
        if errors:
            facts["blunders_per_game_recent"] = round(errors[-1]["blunders_mean"], 2)
            if len(errors) >= 2 * s["noise"]["window"]:
                facts["blunders_per_game_earlier"] = round(errors[s["noise"]["window"] - 1]["blunders_mean"], 2)
        if s.get("motifs"):
            facts["top_blunder_motifs"] = [m["motif"] for m in s["motifs"][:3]]
        if s.get("clock"):
            facts["clock_share_left_at_move_30"] = s["clock"]["median_share_at_30"]
            facts["time_trouble_blunder_share"] = s["clock"]["time_trouble_blunder_share"]
    g = conn.execute(
        "SELECT COUNT(*) n, SUM(result='win') w, SUM(result='draw') d, SUM(result='loss') l FROM games "
        "WHERE played_at >= ? AND platform NOT IN ('pgn')",
        (since,),
    ).fetchone()
    facts.update(games_this_week=g["n"], wins=g["w"] or 0, draws=g["d"] or 0, losses=g["l"] or 0)
    r = conn.execute(
        "SELECT COUNT(*) n, SUM(correct) ok, SUM(correct = 0 AND confidence = 'sure') cm FROM reviews "
        "WHERE at >= ? AND mode = 'standard'",
        (since,),
    ).fetchone()
    facts.update(solve_attempts=r["n"], solve_correct=r["ok"] or 0, confident_misses=r["cm"] or 0)
    e = conn.execute("SELECT COUNT(*) n, SUM(correct) ok FROM reviews WHERE at >= ? AND mode = 'endgame'", (since,)).fetchone()
    facts.update(endgame_attempts=e["n"], endgame_successes=e["ok"] or 0)
    c = conn.execute(
        "SELECT COUNT(*) n, SUM(first_correct) ok, SUM(saw_it) saw FROM calc_attempts WHERE at >= ?", (since,)
    ).fetchone()
    facts.update(calc_attempts=c["n"], calc_first_move_correct=c["ok"] or 0, calc_saw_answer_among_candidates=c["saw"] or 0)
    facts["post_mortems_filed"] = conn.execute("SELECT COUNT(*) FROM lab_sessions WHERE closed_at >= ?", (since,)).fetchone()[0]
    facts["lessons_this_week"] = [
        r[0] for r in conn.execute("SELECT text FROM lessons WHERE created_at >= ? ORDER BY id", (since,))
    ][:6]
    plan = planner.today(conn, now)
    facts["stage"] = plan["stage"]["stage"]
    facts["stage_allocation_percent"] = plan["allocation"]
    facts["minutes_planned_this_week"] = sum(d["planned"] for d in plan["week"])
    facts["minutes_done_this_week"] = sum(d["done"] or 0 for d in plan["week"])
    cal = calibration.status(conn)
    if cal["last"]:
        facts["last_calibration_performance"] = cal["last"]["performance"]
    return facts


def _fact_numbers(facts: Any) -> set[str]:
    """Every number in the facts, in the textual forms a writer might use."""
    out: set[str] = set()

    def add(v: float) -> None:
        out.update({str(v), f"{v:g}", str(round(v)), str(abs(round(v)))})
        if isinstance(v, float) and 0 <= v <= 1:
            out.update({str(round(v * 100)), f"{round(v * 100)}%"})

    def walk(x: Any) -> None:
        if isinstance(x, bool):
            return
        if isinstance(x, int | float):
            add(x)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            for m in NUMBER.findall(x):
                out.add(m.lstrip("+−-").rstrip("%"))

    walk(facts)
    return out


def ground_weekly(out: dict[str, Any], facts: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    allowed = _fact_numbers(facts)
    removed: list[str] = []

    def grounded(text: str) -> bool:
        for n in NUMBER.findall(text):
            core = n.lstrip("+−-").rstrip("%").replace(",", "")
            if core not in allowed and n.rstrip("%") not in allowed and core not in {"0", "1", "2", "3"}:
                return False
        return True

    obs = []
    for o in out.get("observations", []):
        keys = [k for k in o.get("evidence", []) if k in facts]
        if grounded(o.get("text", "")) and keys:
            obs.append({"text": o["text"], "evidence": keys})
        else:
            removed.append(o.get("text", ""))
    headline = out.get("headline", "")
    if not grounded(headline):
        removed.append(headline)
        headline = "Your week in gambit."
    mix = {a: max(0, int(out.get("next_week", {}).get(a, 0))) for a in ACTIVITIES}
    total = sum(mix.values()) or 1
    mix = {a: round(v * 100 / total) for a, v in mix.items()}
    focus = []
    for f in out.get("focus", []):
        (focus if grounded(f) else removed).append(f)
    focus = focus[:3]
    return {"headline": headline, "observations": obs, "next_week": mix, "focus": focus}, removed


def ground_explain(
    out: dict[str, Any], lines_san: list[list[str]], evals: list[str], played: str
) -> tuple[dict[str, Any], list[str]]:
    moves_ok = {m.rstrip("+#") for line in lines_san for m in line} | {played.rstrip("+#")}
    evals_ok = {e.replace("−", "-") for e in evals}
    removed: list[str] = []

    def grounded(text: str) -> bool:
        if any(t.rstrip("+#") not in moves_ok for t in SAN_TOKEN.findall(text)):
            return False
        return all(e.replace("−", "-") in evals_ok for e in EVAL.findall(text))

    points = []
    for p in out.get("points", [])[:4]:
        (points if grounded(p) else removed).append(p)
    summary = out.get("summary", "")
    if not grounded(summary):
        removed.append(summary)
        summary = ""
    return {"summary": summary, "points": points}, removed


# ── Ollama ───────────────────────────────────────────────────────────────────────────────────────


class Ollama:
    """The local model server. https://github.com/ollama/ollama/blob/main/docs/api.md"""

    NOT_RUNNING = "Ollama isn't running. Open the Ollama app, or run ollama serve in a terminal."

    def __init__(self, url: str = config.OLLAMA_URL, transport: httpx.AsyncBaseTransport | None = None):
        self.url, self.transport = url, transport

    def _http(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.url, transport=self.transport, timeout=httpx.Timeout(timeout, connect=3))

    async def status(self) -> dict[str, Any]:
        try:
            async with self._http(5) as http:
                version = (await http.get("/api/version")).json().get("version")
                tags = (await http.get("/api/tags")).json().get("models", [])
        except (httpx.HTTPError, ValueError):
            return {"running": False, "version": None, "models": []}
        models = [
            {
                "name": m["name"],
                "size": m.get("size"),
                "params": (m.get("details") or {}).get("parameter_size"),
                "quant": (m.get("details") or {}).get("quantization_level"),
            }
            for m in tags
            if m.get("name")
        ]
        return {"running": True, "version": version, "models": sorted(models, key=lambda m: m["name"])}

    async def chat(self, model: str, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        body = {
            "model": model,
            "stream": False,
            "format": schema,
            "keep_alive": config.COACH_KEEP_ALIVE,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": config.COACH_TEMPERATURE, "num_ctx": config.COACH_NUM_CTX},
        }
        try:
            async with self._http(config.COACH_TIMEOUT) as http:
                r = await http.post("/api/chat", json=body)
        except httpx.ConnectError as e:
            raise CoachError(self.NOT_RUNNING) from e
        except httpx.TimeoutException as e:
            raise CoachError(f"{model} took longer than {config.COACH_TIMEOUT // 60} minutes. Try a smaller model.") from e
        except httpx.HTTPError as e:
            raise CoachError(f"Couldn't talk to Ollama: {e}") from e
        if r.status_code == 404:
            raise CoachError(f"{model} isn't installed in Ollama. Choose another in Settings, or run ollama pull {model}.")
        if r.status_code != 200:
            try:
                detail = r.json().get("error") or r.text
            except ValueError:
                detail = r.text
            raise CoachError(f"Ollama returned an error: {detail[:200]}")
        try:
            out = json.loads(r.json()["message"]["content"])
        except (ValueError, KeyError, TypeError) as e:
            raise CoachError("The coach's answer couldn't be read. Try again.") from e
        if not isinstance(out, dict):
            raise CoachError("The coach's answer couldn't be read. Try again.")
        return out


# ── The coach ────────────────────────────────────────────────────────────────────────────────────


class Coach:
    def __init__(
        self, conn: sqlite3.Connection, analyse_multi: MultiAnalyse, locked: Callable[[], bool], ollama: Ollama | None = None
    ):
        self.conn, self.analyse_multi, self.locked = conn, analyse_multi, locked
        self.ollama = ollama or Ollama()

    def model(self) -> str:
        return (get_setting(self.conn, "coach_model") or "").strip()

    async def status(self) -> dict[str, Any]:
        st = await self.ollama.status()
        model = self.model()
        return {**st, "model": model or None, "installed": any(m["name"] == model for m in st["models"])}

    def _ready(self) -> str:
        if self.locked():
            raise CoachError("The fair-play lock is on. The coach is off until your live game is over.")
        model = self.model()
        if not model:
            raise CoachError("Choose a local model for the coach in Settings.")
        return model

    async def _ask(self, system: str, payload: dict[str, Any], schema: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        model = self._ready()
        return model, await self.ollama.chat(model, system, json.dumps(payload, ensure_ascii=False), schema)

    def _store(self, kind: str, model: str, payload: dict[str, Any], output: dict[str, Any]) -> None:
        with tx(self.conn):
            self.conn.execute(
                "INSERT INTO coach_reports (kind, created_at, model, input, output) VALUES (?,?,?,?,?)",
                (kind, int(time.time()), model, json.dumps(payload), json.dumps(output)),
            )

    def latest(self) -> dict[str, Any] | None:
        r = self.conn.execute(
            "SELECT created_at, model, input, output FROM coach_reports WHERE kind = 'weekly' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if r is None:
            return None
        return {"created_at": r["created_at"], "model": r["model"], "facts": json.loads(r["input"]), **json.loads(r["output"])}

    async def weekly(self) -> dict[str, Any]:
        facts = weekly_facts(self.conn)
        model, raw = await self._ask(WEEKLY_SYSTEM, {"facts": facts}, WEEKLY_SCHEMA)
        grounded, removed = ground_weekly(raw, facts)
        out = {**grounded, "removed": len(removed)}
        self._store("weekly", model, facts, out)
        return {"created_at": int(time.time()), "model": model, "facts": facts, **out}

    async def explain(self, fen: str, played_uci: str, level: int | None = None) -> dict[str, Any]:
        self._ready()  # fail fast: model and lock
        board = chess.Board(fen)
        move = chess.Move.from_uci(played_uci)
        if move not in board.legal_moves:
            raise CoachError("That move isn't legal in this position.")
        played_san = board.san(move)
        lines = await self.analyse_multi(fen, config.LAB_ENGINE_NODES, 3)
        sign = 1 if board.turn == chess.WHITE else -1
        shown, sans, evals = [], [], []
        for ev, pv in lines:
            b, san_line = board.copy(), []
            for u in pv[:6]:
                m = chess.Move.from_uci(u)
                if m not in b.legal_moves:
                    break
                san_line.append(b.san(m))
                b.push(m)
            text = f"mate in {abs(ev.mate)}" if ev.mate is not None else f"{sign * ev.clamped() / 100:+.2f}"
            shown.append({"line": san_line, "eval": text})
            sans.append(san_line)
            evals.append(text)
        after = board.copy()
        after.push(move)
        played_eval = None
        if not after.is_game_over():
            (ev2, pv2), *_ = await self.analyse_multi(after.fen(), config.LAB_ENGINE_NODES, 1)
            # White-POV eval after your move, shown from your side like the lines above.
            played_eval = f"{sign * ev2.clamped() / 100:+.2f}" if ev2.mate is None else f"mate in {abs(ev2.mate)}"
            evals.append(played_eval)
            b, reply = after.copy(), []
            for u in pv2[:4]:
                m = chess.Move.from_uci(u)
                if m not in b.legal_moves:
                    break
                reply.append(b.san(m))
                b.push(m)
            sans.append(reply)
        payload = {
            "fen": fen,
            "side_to_move": "white" if board.turn else "black",
            "player_rating": level,
            "chosen_move": played_san,
            "chosen_move_eval": played_eval,
            "chosen_move_reply_line": sans[-1] if played_eval is not None else [],
            "stockfish_lines": shown,
        }
        model, raw = await self._ask(EXPLAIN_SYSTEM, payload, EXPLAIN_SCHEMA)
        grounded, removed = ground_explain(raw, sans, evals, played_san)
        out = {**grounded, "removed": len(removed), "lines": shown, "played": played_san, "played_eval": played_eval}
        self._store("explain", model, payload, out)
        return out
