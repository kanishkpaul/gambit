import type { Platform } from './types'

export const PLATFORM: Record<Platform, string> = { chesscom: 'Chess.com', lichess: 'Lichess' }

export const MOTIF: Record<string, string> = {
  allowed_mate: 'Allowed a forced mate',
  back_rank: 'Back-rank weakness',
  missed_mate: 'Missed a forced mate',
  hung_piece: 'Left a piece hanging',
  fork: 'Walked into a fork',
  pin: 'Walked into a pin',
  discovered_attack: 'Missed a discovered attack',
  missed_capture: 'Missed a free capture',
  lost_material: 'Lost material to a combination',
  positional: 'No quick tactic',
}

export const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

export const poolName = (p: { platform: Platform; time_class: string }) => `${PLATFORM[p.platform]} ${p.time_class}`

const nf = new Intl.NumberFormat('en-GB')
export const num = (n: number | null | undefined) => (n == null ? '–' : nf.format(n))
export const pct = (x: number | null | undefined, digits = 0) => (x == null ? '–' : `${(x * 100).toFixed(digits)}%`)
export const signed = (n: number) => `${n > 0 ? '+' : n < 0 ? '−' : '±'}${nf.format(Math.abs(Math.round(n)))}`

const dShort = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' })
const dLong = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
export const date = (unix: number) => {
  const d = new Date(unix * 1000)
  return d.getFullYear() === new Date().getFullYear() ? dShort.format(d) : dLong.format(d)
}
export const dateLong = (unix: number) => dLong.format(new Date(unix * 1000))

export function duration(s: number | null | undefined): string {
  if (s == null) return '–'
  if (s < 90) return `${Math.round(s)} s`
  const m = Math.round(s / 60)
  if (m < 90) return `${m} min`
  const h = Math.floor(m / 60)
  return `${h} h ${String(m % 60).padStart(2, '0')} min`
}

export function timeControl(tc: string | null): string {
  if (!tc) return 'Daily'
  const [base, inc] = tc.split('+').map(Number)
  const mins = base >= 60 ? `${base / 60}` : `${base}s`
  return inc ? `${mins}+${inc}` : mins
}

/** Lichess puzzle themes and our motif keys, in words. */
const THEME_WORDS: Record<string, string> = {
  hangingPiece: 'Hanging piece', mateIn1: 'Mate in 1', mateIn2: 'Mate in 2', mateIn3: 'Mate in 3', mateIn4: 'Mate in 4',
  mateIn5: 'Mate in 5+', backRankMate: 'Back-rank mate', defensiveMove: 'Defensive move', oneMove: 'One move',
  crushing: 'Crushing', advantage: 'Advantage', equality: 'Equality', short: 'Short', long: 'Long', veryLong: 'Very long',
}
const HIDDEN_THEMES = new Set(['oneMove', 'short', 'long', 'veryLong', 'master', 'masterVsMaster', 'superGM'])

export function themeWords(t: string): string {
  if (MOTIF[t]) return MOTIF[t]
  if (THEME_WORDS[t]) return THEME_WORDS[t]
  const words = t.replace(/([a-z])([A-Z0-9])/g, '$1 $2').toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

export const visibleThemes = (ts: string[]) => ts.filter((t) => !HIDDEN_THEMES.has(t) && t !== 'positional')

export function days(d: number | null): string | null {
  if (d == null) return null
  if (d < 1 / 24) return `in about ${Math.max(1, Math.round(d * 1440))} min`
  if (d < 1) return `in ${Math.max(1, Math.round(d * 24))} h`
  if (d < 1.5) return 'tomorrow'
  if (d < 45) return `in ${Math.round(d)} days`
  return `in ${Math.round(d / 30)} months`
}
