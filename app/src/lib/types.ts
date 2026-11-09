// Shapes returned by the brain. Kept in step with brain/gambit_brain/{server,metrics,audit}.py.

export type Platform = 'chesscom' | 'lichess'

export interface Settings {
  chesscom_username: string
  lichess_username: string
  training_start: number | null
  fairplay_lock: boolean
  has_lichess_token: boolean
  has_anthropic_key: boolean
  engine: { workers: number; nodes: number; deep_nodes: number }
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
  mode: 'standard' | 'speed'
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
  mode: 'standard' | 'speed'
  fen: string
  lead_uci: string | null
  played: string[]
  replies: string[]
  turn: 'white' | 'black'
  elapsed_min: number
  timebox_min: number
}

export interface SolveSummary {
  mode: 'standard' | 'speed'
  attempted: number
  solved: number
  confident_misses: number
  median_ms: number | null
  minutes: number
  planned: number
  solve_rating: number
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
