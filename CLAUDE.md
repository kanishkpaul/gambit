# Gambit

A personal macOS chess tutor for one player. It is not distributed, so optimise for this player's training, not for general users.

- Product plan and build order: `docs/PLAN.md`
- Design language and quality bar: `docs/DESIGN.md`

## Non-negotiables

1. **The UI/UX must be premium.** Treat every screen as design work, follow `docs/DESIGN.md`, and run its quality-bar checklist before calling UI done. No default component-library look. Load the `frontend-design` and `ui-ux-pro-max` skills before building UI, and `dataviz` before any chart.
2. **Fair play.** No engine, Maia or coach assistance while a live game is in progress. Analysis runs on finished games only.
3. **Solve first, reveal later.** Training boards never show evaluations, best moves or hints before the user commits to an answer.
4. **Guardrails stay on.** Time-boxes, stopping rules, stop-loss, no streaks or quotas. Don't add gamification.
5. **The coach is grounded.** The Claude coach may only state evaluations and lines confirmed by Stockfish output passed into its prompt.
6. **Local first.** Data lives in SQLite on the Mac. Secrets (Lichess token, Claude API key) go in the macOS Keychain, never in files or the repository.

## Stack

- Tauri 2 shell; React and TypeScript UI with chessground and chessops
- Python 3.12 brain: python-chess, Stockfish 18+ (UCI), Maia-3 (CSSLab, PyTorch on MPS), FSRS
- SQLite storage
- External: Chess.com public API, Lichess API, Claude API

## Conventions

- Don't commit engine binaries, model weights, puzzle databases or user data (see `.gitignore`).
- Keep rating conversions, thresholds and stage allocations in one config module, not scattered constants.
