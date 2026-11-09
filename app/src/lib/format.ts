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
