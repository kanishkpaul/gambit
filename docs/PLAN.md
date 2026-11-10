# Product plan

gambit is a personal Mac chess tutor for one player. Its design follows research on accelerated skill acquisition and chess expertise (kept outside this repository).

## Core model

1. **Rating below master level mostly measures the error tail.** Large errors fall roughly by half for every ~600 Elo, so the fastest early gains come from eliminating hung pieces and missed threats.
2. **Recognition carries most of the strength.** Blitz performance reproduces up to ~81% of rating variance, so most hours should build a library of patterns you recognise instantly. Chess patterns are tied to particular squares, so each one needs varied instances across board sectors and both colours.
3. **Solving is retrieval practice** (g ≈ 0.6 over restudy). Spacing (d ≈ 0.46) and mixing visually similar categories (g ≈ 0.67) make it stick.
4. **Study beats play per hour** (~3.6× on Chess.com data). Games are tests and raw material for analysis.
5. **Rating is noisy.** ±40 points of standard deviation at fixed skill, and 90-point swings within 50 games are normal. Steer by rolling averages per games played and by leading indicators.

## Stack (locked 2026-11-09)

Decided by the stack evaluation (research report 06). Native SwiftUI is the runner-up and replaces only the UI layer if the bake-off triggers it (see below).

| Layer | Owner | Choice |
|---|---|---|
| UI | TypeScript + React | `@lichess-org/chessground` 10.5 (thin in-house React wrapper), `chessops` 0.15 for client-side legality/SAN/mirroring, Tailwind 4 + shadcn source restyled to `DESIGN.md`, Motion, cmdk (⌘K), Observable Plot (visx/D3 where bespoke) |
| Shell | Rust (thin) | Tauri 2.12: windows, menus, settings, `window-vibrancy`, Keychain via `keyring`, supervises the brain. Plain `std::process`/tokio spawning, no bundled sidecar |
| Brain | Python 3.12 (pinned), run with `uv run` | One long-lived asyncio process that owns everything below |
| Chess logic | Python | python-chess 1.11.x; vendored, adapted lichess-puzzler tagger |
| Engines | Python | Pool of Stockfish 19 processes via `chess.engine`: N × Threads=1 for batch, 1 × Threads=3 for live. Validate FENs first (SF19 exits on invalid input) |
| ML | Python | Maia-3 (CSSLab, pinned commit) called through its model code, not `maia3-uci`; Maia-2 Rapid alongside for rapid play; ONNX Runtime export as a benchmarked alternative backend |
| Review | Python | py-fsrs (FSRS-6) with optimizer |
| Storage | Python, single writer | stdlib `sqlite3`, WAL, one file; Lichess puzzle CSV imported once |
| APIs | Python | berserk for Lichess (personal token with `puzzle:read`; explorer needs the token); `httpx` for Chess.com PubAPI (serial, generic User-Agent, ETag) |
| Coach | Python | A local model through Ollama (`/api/chat` with a JSON-schema `format`), chosen in Settings; free and offline; grounded in Stockfish output. (Was the Claude API until 2026-11-09; dropped: no paid services.) |

### Process architecture

```
gambit.app (Tauri, Rust) ── reads Keychain, spawns brain, owns windows/menus
   │  spawn: uv run --frozen --project brain python -m gambit_brain
   │  stdin: init {lichess_token, ws_token}; EOF = brain exits
   ▼
WKWebView (React) ── JSON-RPC over ws://127.0.0.1:<port>?t=<ws_token>
   ▼
gambit_brain (Python 3.12) ── SQLite · Maia (warm) · FSRS · tagger · coach · Stockfish pool
```

- The brain also polls its parent PID and exits if the shell dies. Every quit path must leave zero orphans.
- Secrets flow Rust → brain over stdin; they never enter the WebView and Python never touches the Keychain.
- The WebSocket lets the full stack run in a normal browser during development (`uv run gambit_brain --dev` + Vite), so UI work can be verified with browser tooling.
- Batch analysis defaults to ~100k nodes per position on 4 workers (measured: ~4 h per 2,000 games on this M5 Air), skips positions that already have a Lichess eval, and re-searches only critical moments at 1M+ nodes. See `bakeoff/RESULTS.md`.
- The fair-play lock suspends the Stockfish pool and Maia, not just the panels.
- Never fine-tune a model on Chess.com games (User Agreement §4(D)); use Lichess CC0 data.
- Sign dev builds with one stable identity so the Keychain doesn't re-prompt.

### Runner-up trigger

Switch the UI layer to native SwiftUI (keeping the brain and protocol unchanged) if any of these happens: the board can't meet the motion spec without heavy patching; the native-feel audit fails on things CSS can't fix; or the owner prefers a SwiftUI board spike in a side-by-side comparison. Also re-test if training moves to a 120 Hz+ display.

## Modules

| Module | What it does |
|---|---|
| **Mirror** | Imports all games, runs batch analysis and tags each move: blunder ≥ 2 pawns, mistake, motif, phase, time spent, clock left. Includes a one-time history audit that is time-boxed, then filed and closed. |
| **Solve** | Draws positions from your own blunders, Lichess puzzles on the themes you miss, and positions where Maia predicts players at your level go wrong. You commit to a move, line and confidence before anything is revealed. Sets are mixed and unlabelled, with varied instances of each motif, FSRS review, and a timed speed mode. |
| **Calculation** | The pieces stay frozen while you list candidates and type the main line, then the engine verifies it. Includes a visualization mode and a "scan one different area once" step. |
| **Game Lab** | The engine stays locked until you've annotated the game and logged 1–3 critical moments. Then come Stockfish, Maia at your level versus a higher level, and time use plotted against criticality. Sessions are time-boxed and end with lessons logged into review. |
| **Endgames** | A curriculum of theoretical positions played against tablebase defence, with spaced review. |
| **Openings** | A narrow repertoire built from your own games. Flags where you left your preparation and reviews only critical lines; its share of time is capped by stage. |
| **Sparring** | Local Maia-3 set slightly above your level at long time controls, plus an optional "good-enough move" drill. |
| **Master games** | Guess-the-move through games in the pawn structures your repertoire leads to. |
| **Planner** | Daily sessions split by stage allocations, which advance automatically with rating. Rest days and variety are built in. |
| **Slope** | Rolling 50–100-game rating against games played with the noise band shaded, blunders per game, clock profile, Maia band resemblance, hours logged against the plan, and progress gates. |
| **Calibration** | Every 6–8 weeks, a fresh difficulty-matched set solved cold and timed. |
| **Coach** | A weekly review of your metrics, a proposed mix for the next week, and plain-language explanations of engine-confirmed lines. |

### Stage allocations (starting point, untested)

| Activity | Stage 1 | Stage 2 | Stage 3 | Stage 4 |
|---|---|---|---|---|
| Solving (tactics → calculation) | 35% | 30% | 25% | 20% |
| Own-game analysis | 20% | 20% | 20% | 15% |
| Endgames | 15% | 15% | 15% | 10% |
| Master games, structures | 5% | 15% | 15% | 15% |
| Openings | 5% | 5% | 10% | 20% |
| Serious play | 20% | 15% | 15% | 20% |

### Gates

| Gate | Target | Meaning |
|---|---|---|
| 0 · ~6 months | Rolling average clearly beating the ordinary-adult rate (~+95/yr) | Method check: if it isn't, change the content, not the volume |
| 1 · year 3–4 | FIDE ~2000 | Key checkpoint |
| 2 · year 6 | FIDE ~2200 | Key checkpoint |

## Guardrails

- **Fair-play lock:** all assistance is off while a live game is in progress. Lichess games are detected through the API; Chess.com uses a manual toggle.
- **Time-boxes** on every session, with a soft warning and then a hard stop.
- **Stop-loss:** stop playing after 2–3 straight losses, or after any loss that leaves you angry.
- **Engine-reassurance limiter:** a nudge after repeated engine checks of the same position.
- **Post-mortem stopping rule:** 1–3 lessons, then the file closes.
- **Diminishing returns warning:** flags when time on an activity grows while measured benefit shrinks.
- **No streaks, quotas or daily shame mechanics.**

## Build notes

### v0.1 · Mirror (built 2026-11-09)

- **Import.** Chess.com monthly archives with ETags (the last two months are re-checked each time); Lichess `/api/games/user` as NDJSON with `since`, clocks, evals and openings. Both use `httpx` directly rather than berserk, so one client handles streaming, the 429 wait and the cursor. Standard chess only.
- **Analysis.** First pass at 100k nodes on 4 single-thread workers, newest games first, three games in flight; positions are deduplicated by EPD across games, and Lichess server evals are reused. Then a deep pass re-searches your blunders (the position before and after) at 1M nodes and reclassifies.
- **Classification.** Evaluations clamped to ±1000; blunder ≥ 200 cp, mistake ≥ 100, inaccuracy ≥ 50, never an error while the mover stays ≥ +300. Time trouble is < 10% of base time left.
- **Motifs.** An in-house starter tagger reads the refutation line: allowed or missed mate, back rank, hung piece, fork, pin, discovered attack, missed capture, lost material, else positional. The lichess-puzzler tagger comes with Solve.
- **Mirror hides answers.** It shows counts and where errors happened, never best moves, because those positions become Solve items.
- **Slope.** Rating against rated games played per platform and time class, a rolling 50-game mean, and a ±2 SD band (±80 Chess.com, ±60 Lichess). Ratings are a random walk, so a trend is drawn only when the rolling mean has moved more than the band over at least 50 games. Blunders per game, clock at move 30, losses on time, errors by phase and motif, and Gate 0 from the training start date. Maia band resemblance arrives with Maia.
- **Audit.** One row, ever: a snapshot report with a 45-minute time-box (warning at 40), then 1–3 lessons and it closes. It includes your score after two straight losses, the evidence for the stop-loss rule.
- **Fair-play lock.** A manual switch for now; it cancels the batch job and kills the Stockfish pool. Lichess live-game detection comes with v0.3.

### v0.2 · Solve (built 2026-11-09)

- **Library.** The Lichess puzzle CSV (310 MB zstd, ~5.9M puzzles) is streamed, decompressed on the fly and filtered to popularity ≥ 90, 1,000+ plays and rating deviation ≤ 90: about 1.5M puzzles, ~250 MB. Rerunning updates ratings in place.
- **Own positions.** Every deep-checked blunder of yours (unless you were already lost) becomes an item that starts one move earlier, with the opponent's move as the lead-in, plus a colour-mirrored twin for variety. Alternatives within 50 cp of the best move are accepted, checked live by a 3-thread Stockfish (exact answers only while the fair-play lock is on).
- **Sets.** 20 positions or 30 minutes: due reviews first (up to 12), then up to 6 new own positions, then library puzzles drawn by theme weight (Stage-1 error-tail themes, boosted by your own blunder motifs) at your solve rating − 100. Interleaved so the same theme or side to move rarely repeats. Unlabelled until answered.
- **Solve first.** The client receives only the position; solutions stay in the brain until the item ends. On the first move you commit a move, an optional expected line and a confidence (guess / unsure / sure).
- **Grading.** Wrong → Again; guess → Hard; unsure or slow sure → Good; sure under 20 s → Easy. FSRS-6 with 0.9 retention and 10-minute (re)learning steps. Any mate solves a mate puzzle. "Sure but wrong" is tracked as a calibration signal.
- **Solve rating.** Elo-style on the Lichess puzzle scale from first attempts at library puzzles in standard sets, starting at 1200.
- **Speed run.** 5 minutes of puzzles 300 below your solve rating; moves count immediately; no FSRS cards and no rating change.
- **Board.** chessground with the spring-easing patch, the Cburnett piece set (see [third-party notices](THIRD_PARTY.md)), walnut on slate, typed SAN on every position.

### v0.3 · Game Lab (built 2026-11-09)

- **Engine locked first.** A post-mortem opens with the game only. You comment on moves and flag 1–3 critical moments (what you thought, what you'd play now). The unlock is refused until at least one moment is logged, and the view sent to the UI carries no engine or Maia data before that.
- **Reveal.** Evaluations for every position (reusing batch analysis, filling gaps at 300k nodes), your moves classified, the engine's three costliest errors of yours against the moments you picked ("you found 1 of 3"), best lines for both, Maia-3 at your level and 400 above for each moment, the level whose Maia best explains your moves (shown as a resemblance, never a rating), and time spent against what was at stake.
- **Maia.** Maia-3 23M through its model code on CPU, history-aware, 17 levels (800–2400) in one batched pass: about 1 s per game after a ~5 s first load. It unloads when the fair-play lock comes on.
- **Guardrails.** 45-minute time-box (warning at 40; after it, annotations freeze and only the unlock and filing remain). Engine checks of a position you're exploring nudge you towards writing a lesson after the third. Filing needs 1–3 lessons, closes the file for good, and turns your flagged and the engine's critical positions (where you erred by ≥ 1 pawn) into Solve items. One open post-mortem at a time.
- **Pasted PGN.** Finished games from anywhere (over-the-board included) can be pasted; unfinished games are refused.
- **Fair-play lock.** Lichess's public status endpoint is polled every 30 s: the lock turns on during a Lichess game and off after it; a manual lock is never lifted automatically.
- **Stop-loss.** A banner after 2 straight losses today and a stop after 3, or for the rest of the day after "that loss made me angry" (command palette).

### v0.4 · Train (built 2026-11-09)

- **Today.** The day's minutes (weekly hours ÷ training days; default 20 h, Sunday off) split by the stage allocation. Unbuilt modules fold into Solve (master games) and Game Lab (openings). Study blocks rotate daily for variety; play always comes last. Time done is measured from Solve sets, post-mortems, endgame attempts and games, never typed in; the week shows plan against actual, with no streaks. The stage follows the rolling rating of your headline pool (Chess.com rapid 1600 / 2000 / 2200; Lichess +200, approximate), or a manual override.
- **Endgames.** 11 positions in three stages (basic mates, king and pawn, rook pawn, Lucena, Philidor, rook against pawn, two bishops, bishop and knight), each verified against the Lichess tablebase. Played against perfect tablebase defence, randomly mirrored left–right and colour-flipped. A move that throws the result away ends the attempt and shows the moves that kept it; the idea is shown only afterwards. FSRS schedules each position (Easy when done within 2 moves of optimal).
- **Sparring.** Maia-3 79M, its policy sampled at the chosen level (not its top move, which plays above its label), with human-paced thinking time charged to its clock. Long time controls only (15+10 to 60+30), no engine during the game. Games are saved (platform `sparring`, never counted for the stop-loss) and open straight into Game Lab. Results are tracked per level.
- **Human-level labels.** Maia-3 learned only from Lichess blitz, so its levels are on that scale, and the research found no trustworthy published conversion at beginner-to-club level. So gambit measures one: every game gets a Maia fit for both sides (log-likelihood totals at 21 levels, 600–2600, with a likelihood interval), and your rating against the level your own moves resemble, pooled over 15–40 recent rated games, gives a personal offset. Any level (a sparring bot, or any opponent, including other sites' bots via a pasted PGN) is then shown as "plays like a Chess.com rapid ~X player", with a likely range, relative to your own moves, and a pooled profile across repeat games. A fit at either end of Maia's range is shown as "or stronger"/"or weaker", never as a number. Your results against each level check the label.
- **Background.** New games are fetched every 30 minutes and as soon as a Lichess game ends; the Maia fits run after analysis.

### v0.5 · Deepen (built 2026-11-09)

- **Calculation.** Long library puzzles (themes long / veryLong) near your level, never repeated. The board stays frozen: up to four candidates, then the full line you believe, then one deliberate look at another part of the board, then Stockfish scores where your line ends against where the best line ends. Tracks first-move accuracy, "saw it but chose otherwise" (the answer was among your candidates) and line depth. Visualization mode hides the pieces after 12 seconds.
- **Openings.** Your repertoire is the move you play most (2+ games) in each position of your first eight moves, per colour, or a move you pin. Leaks are repertoire moves the batch analysis says lose 0.7+ pawns, with the engine's preferred move and a one-click switch. Each recent game shows where it left your repertoire. Only positions where you actually deviated become drill items, on FSRS.
- **Master games.** Classical over-the-board games from Lichess broadcasts (public; both players 2300+, finished, 40+ plies). Games sharing one of your repertoire positions at least two moves deep come first. You guess one side's moves from move 9 for 20 moves; a guess within 0.3 pawns of the master's move (checked by Stockfish) counts as just as good.
- **Calibration.** Every 42 days: 20 never-seen puzzles spread from your solve rating − 300 to + 300, 90 seconds each, one attempt, nothing revealed or scheduled, and no effect on the solve rating. The result is a performance rating on the puzzle scale, tracked across tests.
- **Coach.** A local model through Ollama, picked in Settings from the installed models (originally Claude Opus 5.5; switched the same day so gambit uses no paid services). Output is constrained to a JSON schema. The weekly review sees only a facts object gambit computes; observations whose numbers aren't in it, or that cite no real fact key, are removed before display, and the proposed split is renormalised to 100%. Explanations see only Stockfish's top three lines and the reply to your move; any point naming a move or evaluation not in those lines is removed. Everything sent and returned is stored. Off under the fair-play lock; needs Ollama running with the chosen model.
- **Planner.** Openings and master games now get their own share instead of folding into Solve and Game Lab.

## Build order

1. **v0.1 · Mirror:** import, batch analysis, Slope dashboard, one-time audit. *(built; see Build notes)*
2. **v0.2 · Solve:** positions from your own blunders + Lichess puzzle library, solve-first, FSRS. *(built; see Build notes)*
3. **v0.3 · Game Lab:** engine-locked post-mortems, Maia comparison, fair-play lock, guardrails. *(built; see Build notes)*
4. **v0.4 · Train:** planner, endgames, Maia sparring, human-level labels for any opponent. *(built; see Build notes)*
5. **v0.5 · Deepen:** calculation, openings, master games, local coach, calibration. *(built; see Build notes)*
