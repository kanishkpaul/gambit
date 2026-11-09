// Shapes returned by the brain. Kept in step with brain/gambit_brain/{server,metrics,audit}.py.

export type Platform = 'chesscom' | 'lichess'

export interface Settings {
  chesscom_username: string
  lichess_username: string
  training_start: number | null
  fairplay_lock: boolean
  fairplay_reason: 'manual' | 'lichess' | null
  has_lichess_token: boolean
  coach_model: string
  engine: { workers: number; nodes: number; deep_nodes: number }
  weekly_hours?: number
  rest_days?: number[]
  stage_override?: number | null
}

export interface AnalysisStatus {
  state: 'idle' | 'running' | 'pausing' | 'paused' | 'done' | 'error'
  error: string | null
  games: number
  analysed: number
  deep: number
  positions_per_s: number | null
  eta_s: number | null
  phase?: 'first' | 'deep' | null
}

export interface ImportState {
  state: 'idle' | 'running' | 'done' | 'error'
  platform?: Platform | null
  step?: string
  done?: number
  total?: number | null
  stored?: number
  errors?: string[]
  results?: { platform: Platform; seen: number; stored: number }[]
  finished_at?: number
}

export interface Pool {
  platform: Platform
  time_class: string
  n: number
  rated: number
  last: number
}

export interface GameRow {
  id: number
  platform: Platform
  url: string | null
  played_at: number
  time_class: string
  time_control: string | null
  rated: number
  my_color: 'white' | 'black'
  my_rating: number | null
  opp_rating: number | null
  opp_name: string | null
  result: 'win' | 'loss' | 'draw'
  termination: string | null
  opening: string | null
  ply_count: number
  analysed: number
  blunders: number
  mistakes: number
}

export interface MirrorSummary {
  totals: { games: number; chesscom: number | null; lichess: number | null; first: number | null; last: number | null }
  recent: GameRow[]
  pools: Pool[]
  analysis: AnalysisStatus
  import: ImportState
}

export interface RatingPoint { i: number; t: number; rating: number; mean: number; lo: number; hi: number }
export interface ErrorPoint { i: number; t: number; blunders: number; blunders_mean: number; mistakes_mean: number }

export interface SlopeData {
  pools: Pool[]
  pool: { platform: Platform; time_class: string } | null
  noise?: { sd: number; band: number; window: number }
  rating?: RatingPoint[]
  trend?: { from_i: number; to_i: number; from: number; to: number; per_100: number; real: boolean } | null
  errors?: ErrorPoint[]
  phases?: Record<'opening' | 'middlegame' | 'endgame', number>
  motifs?: { motif: string; count: number }[]
  clock?: {
    median_share_at_30: number | null
    games_reaching_30: number
    loss_on_time_share: number | null
    time_trouble_blunder_share: number | null
  }
  gate0?: {
    state: 'no_data' | 'early' | 'beating' | 'behind'
    start?: number
    days?: number
    due_days?: number
    target_per_year: number
    rate_per_year?: number
    games_since?: number
  }
  counts?: { games: number; rated: number; analysed: number }
}

export interface AuditReport {
  empty: boolean
  games: number
  analysed: number
  first: number
  last: number
  by_time_class: Record<string, { games: number; score: number; blunders_per_game: number | null }>
  blunders: number
  motifs: { motif: string; count: number }[]
  phases: Record<'opening' | 'middlegame' | 'endgame', number>
  time_trouble_share: number | null
  first_blunder_move_median: number | null
  openings_worst: { name: string; color: string; games: number; score: number }[]
  openings_best: { name: string; color: string; games: number; score: number }[]
  losses_on_time: number | null
  tilt: { overall: number; after_two_losses: number | null; games_after_two_losses: number }
}

export interface AuditState {
  state: 'none' | 'open' | 'expired' | 'filed'
  started_at?: number
  filed_at?: number
  now?: number
  report?: AuditReport
  lessons?: string[]
  timebox_min: number
  warn_min: number
  max_lessons: number
}

// ── Solve ──────────────────────────────────────────────────────────────────────────────────────

export interface SolveSessionInfo {
  id: number
  mode: 'standard' | 'speed' | 'calibration'
  total: number
  index: number
  started_at: number
  timebox_min: number
  warn_min: number | null
}

export interface SolveOverview {
  due: number
  due_later_today: number
  new_own: number
  library: number
  learning: number
  reviews_today: number
  solve_rating: number
  rated_attempts: number
  set_size: number
  timebox_min: number
  speed_timebox_min: number
  session: SolveSessionInfo | null
}

export interface PuzzleLibrary {
  state: 'idle' | 'running' | 'done' | 'error'
  count: number
  imported_at: number | null
  download_mb: number
  received?: number
  total?: number | null
  kept?: number
  error?: string
}

/** A position to solve. Deliberately carries no solution, themes, rating or source. */
export interface SolvePosition {
  done: false
  item_id: number
  index: number
  total: number
  mode: 'standard' | 'speed' | 'calibration'
  fen: string
  lead_uci: string | null
  played: string[]
  replies: string[]
  turn: 'white' | 'black'
  elapsed_min: number
  timebox_min: number
  time_limit_s: number | null
}

export interface SolveSummary {
  mode: 'standard' | 'speed' | 'calibration'
  attempted: number
  solved: number
  confident_misses: number
  median_ms: number | null
  minutes: number
  planned: number
  solve_rating: number
  performance?: number | null
}

export type SolveNext = SolvePosition | { done: true; reason: 'timebox' | 'complete'; summary: SolveSummary }

export interface Reveal {
  fen: string
  solution: string[]
  solution_san: string[]
  themes: string[]
  source: {
    kind: 'puzzle' | 'own'
    rating?: number
    id?: string
    url?: string
    game_url?: string | null
    played_at?: number
    opp_name?: string | null
    time_class?: string
    platform?: Platform
    move_number?: number
    mirrored?: boolean
  }
  next_review_days: number | null
  solve_rating: number | null
}

export type MoveResult =
  | { result: 'correct'; done: false; reply_uci: string }
  | { result: 'solved' | 'wrong'; done: true; reveal: Reveal; confident_miss: boolean }

// ── Game Lab and guardrails ─────────────────────────────────────────────────────────────────────

export interface LabGameRow {
  id: number
  platform: Platform | 'pgn'
  played_at: number
  time_class: string
  time_control: string | null
  my_color: 'white' | 'black'
  my_rating: number | null
  opp_name: string | null
  opp_rating: number | null
  result: 'win' | 'loss' | 'draw'
  opening: string | null
  ply_count: number
  session_id: number | null
  unlocked_at: number | null
  closed_at: number | null
}

export interface LabGames {
  games: LabGameRow[]
  open_game_id: number | null
  timebox_min: number
}

export interface LabMove {
  ply: number
  san: string
  uci: string
  color: 'white' | 'black'
  clock_ms: number | null
  spent_ms: number | null
}

export interface RevealMove {
  ply: number
  san: string
  uci: string
  color: 'white' | 'black'
  cp_loss: number
  class: 'best' | 'ok' | 'inaccuracy' | 'mistake' | 'blunder'
  spent_ms: number | null
  best_san?: string | null
  best_uci?: string | null
  best_line?: string[]
}

export interface LabReveal {
  evals: number[]
  moves: RevealMove[]
  engine_moments: number[]
  your_moments: number[]
  found: number[]
  maia:
    | {
        self_level: number
        high_level: number
        rating_used: number
        fit: { level: number; levels: number[]; mean_logp: number[]; moves: number } | null
        moves: { ply: number; p_self: number; p_high: number; top_self: string | null; top_high: string | null }[]
        error?: undefined
      }
    | { error: string }
    | null
  human?: { sides: { me?: HumanLevel | null; opp?: HumanLevel | null }; opponent: OpponentProfile | null } | null
  time: {
    moves: { ply: number; spent_s: number | null; stake: number; critical: boolean }[]
    critical_share_of_moves: number | null
    critical_share_of_time: number | null
  }
}

export interface LabView {
  session: {
    id: number
    state: 'annotate' | 'revealed' | 'expired' | 'closed'
    started_at: number
    unlocked: boolean
    closed_at: number | null
    timebox_min: number
    warn_min: number
    max_moments: number
    max_lessons: number
    unlocking: boolean
  }
  game: {
    id: number
    platform: Platform | 'pgn'
    url: string | null
    played_at: number
    time_class: string
    time_control: string | null
    my_color: 'white' | 'black'
    my_rating: number | null
    opp_name: string | null
    opp_rating: number | null
    result: 'win' | 'loss' | 'draw'
    termination: string | null
    opening: string | null
    start_fen: string
    moves: LabMove[]
  }
  notes: Record<string, string>
  moments: { ply: number; note: string; candidate: string | null }[]
  reveal: LabReveal | null
  lessons: string[]
}

export interface GuardStatus {
  stop_loss: { level: 'clear' | 'caution' | 'stop'; streak: number; games_today: number; tilted: boolean; caution_at: number; stop_at: number }
  lichess: { checked_at: number | null; playing: boolean | null }
  fairplay_lock: boolean
  fairplay_reason: 'manual' | 'lichess' | null
}

// ── Train (v0.4) ───────────────────────────────────────────────────────────────────────────────

/** A Maia level in human terms: native Lichess blitz scale, your platform's numbers, relative to you. */
export interface HumanLevel {
  maia_level: number
  lo: number | null
  hi: number | null
  scale: string
  edge?: 'low' | 'high' | null
  personal?: { platform: Platform; time_class: string; rating: number; lo: number | null; hi: number | null; games: number }
  vs_you?: number
  moves?: number
}

export interface PersonalScale {
  platform: Platform
  time_class: string
  ready: boolean
  games: number
  needed?: number
  beyond?: 'low' | 'high'
  rating?: number
  maia_level?: number
  offset?: number
}

export interface OpponentProfile {
  name: string
  games: number
  moves: number
  fit: HumanLevel | null
  stated_rating: number | null
  blunders_per_game: number | null
}

export interface PlanBlock {
  activity: 'solving' | 'analysis' | 'endgames' | 'master_games' | 'openings' | 'play'
  label: string
  view: string | null
  why: string
  minutes: number
  done: number
}

export interface TodayPlan {
  date: string
  rest_day: boolean
  stage: { stage: number; auto: number; override: boolean; basis: { platform: Platform; time_class: string; rating: number; games: number; next_at: number | null } | null }
  blocks: PlanBlock[]
  planned: number
  done: number
  week: { date: string; weekday: number; planned: number; done: number | null; today: boolean }[]
  weekly_hours: number
  rest_days: number[]
  folded: string[]
}

export interface EndgameLesson {
  key: string
  stage: number
  title: string
  goal: 'mate' | 'promote' | 'capture' | 'hold'
  side: 'white' | 'black'
  status: 'new' | 'due' | 'learning'
  due: number | null
  attempts: number
  successes: number
}

export interface EndgameAttempt {
  key: string
  title: string
  goal: EndgameLesson['goal']
  stage: number
  side: 'white' | 'black'
  fen: string
  moves: string[]
  user_moves: number
  move_limit: number
  lead_uci?: string | null
}

export type EndgameMoveResult =
  | { result: 'ok'; done: false; reply_uci: string; user_moves: number; move_limit: number }
  | {
      result: 'success' | 'failed'
      done: true
      reply_uci: string | null
      reason: string | null
      keeping_moves: string[]
      user_moves: number
      optimal_moves: number | null
      idea: string
      next_review_days: number
    }

export interface SparringRecord { level: number; n: number; w: number; d: number; l: number; score: number }

export interface SparringGame {
  you: 'white' | 'black'
  level: number
  label: HumanLevel
  base_s: number
  inc_s: number
  moves: string[]
  clocks: { white: number; black: number }
  claimable_draw: boolean
  reply?: SparringReply
}

export interface SparringReply { uci: string; think_ms: number; clocks: { white: number; black: number }; over?: SparringOver }
export interface SparringOver { result: 'win' | 'loss' | 'draw'; reason: string; game_id: number | null; level: number; record: SparringRecord | null }

export interface SparringOverview {
  suggested_level: number
  your_elo: number
  label: HumanLevel
  record: SparringRecord[]
  game: SparringGame | null
  time_controls: [number, number][]
}

// ── Deepen (v0.5) ──────────────────────────────────────────────────────────────────────────────

export interface CalibrationStatus {
  history: { finished_at: number; attempted: number; solved: number; performance: number | null; mean_rating: number | null }[]
  last: CalibrationStatus['history'][number] | null
  due: boolean
  next_due_at: number | null
  every_days: number
  size: number
  seconds: number
  spread: number
  library_ready: boolean
}

export interface CalcOverview {
  attempts: number
  first_correct: number | null
  saw_but_rejected: number | null
  avg_plies_matched: number | null
  visual_seconds: number
  library_ready: boolean
}

export interface CalcPosition {
  puzzle_id: string
  mode: 'board' | 'visual'
  start_fen: string
  lead_uci: string
  fen: string
  turn: 'white' | 'black'
  visual_seconds: number
}

export interface CalcResult {
  first_correct: boolean
  saw_it: boolean
  plies_matched: number
  line_len: number
  stopped_at: string | null
  your_line: string[]
  best_line: string[]
  best_ucis: string[]
  your_ucis: string[]
  end_cp: number
  best_cp: number
  rating: number
  themes: string[]
  ms: number
  fen: string
}

export interface OpeningsOverview {
  positions: { white: number; black: number }
  lines: { white: { moves: string[]; games: number }[]; black: { moves: string[]; games: number }[] }
  leaks: { color: 'white' | 'black'; fen: string; san: string; ply: number; games: number; cost: number; engine: string | null; pinned: boolean }[]
  departures: { game_id: number; opp_name: string | null; played_at: number; result: string; color: 'white' | 'black'; event: { kind: 'new' | 'deviated'; ply: number; played: string; usual?: string } | null }[]
  drill_due: number
  plies: number
}

export interface DrillPosition { item_id: number; fen: string; lead_uci: string | null; turn: 'white' | 'black'; remaining: number }

export interface MastersOverview {
  games: number
  matching: number
  history: { started_at: number; guesses: number; matched: number; as_good: number; white: string; black: string; event: string }[]
  moves_per_game: number
  current: GuessView | null
}

export interface GuessView {
  session_id: number
  white: string
  black: string
  white_elo: number
  black_elo: number
  event: string | null
  date: string | null
  opening: string | null
  side: 'white' | 'black'
  moves: string[]
  guesses: number
  matched: number
  as_good: number
  remaining: number
  why: 'repertoire' | 'any'
}

export interface GuessResult {
  matched: boolean
  as_good: boolean
  master_uci: string
  master_san: string
  reply_uci: string | null
  done: boolean
  summary?: { guesses: number; matched: number; as_good: number; result: string; white: string; black: string; event: string | null }
}

export interface CoachStatus {
  running: boolean
  version: string | null
  models: { name: string; size: number | null; params: string | null; quant: string | null }[]
  model: string | null
  installed: boolean
}

export interface CoachWeekly {
  created_at: number
  model: string
  facts: Record<string, unknown>
  headline: string
  observations: { text: string; evidence: string[] }[]
  next_week: Record<'solving' | 'analysis' | 'endgames' | 'master_games' | 'openings' | 'play', number>
  focus: string[]
  removed: number
}

export interface CoachExplain {
  summary: string
  points: string[]
  removed: number
  lines: { line: string[]; eval: string }[]
  played: string
  played_eval: string | null
}
