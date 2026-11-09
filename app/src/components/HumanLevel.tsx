import { PLATFORM, num } from '../lib/format'
import type { HumanLevel } from '../lib/types'

/**
 * "Plays like a human rated X", in the most useful terms available: your own platform's numbers
 * once gambit has measured your personal scale, otherwise Maia's native Lichess blitz scale.
 */
export function LevelLabel({ h, subject = 'Plays', size = 'lg', showScale = true }: { h: HumanLevel; subject?: string; size?: 'lg' | 'sm'; showScale?: boolean }) {
  const p = h.personal
  const value = p ? p.rating : h.maia_level
  const lo = p ? p.lo : h.lo
  const hi = p ? p.hi : h.hi
  const where = p ? `${PLATFORM[p.platform]} ${p.time_class}` : h.scale
  return (
    <div className="grid gap-1">
      <div className={size === 'lg' ? 'text-lg font-semibold leading-snug' : 'text-sm'}>
        {subject} like a {where} <span className="tabular">~{num(value)}</span>
        {h.edge === 'high' ? ' or stronger' : h.edge === 'low' ? ' or weaker' : ''} player
      </div>
      <div className="text-2xs text-muted">
        {lo != null && hi != null && lo !== hi && (
          <>
            likely <span className="tabular">{num(lo)}–{num(hi)}</span>
            {h.moves ? ` from ${h.moves} moves` : ''} ·{' '}
          </>
        )}
        {h.vs_you != null &&
          (Math.abs(h.vs_you) < 50 ? 'about your level · ' : `${num(Math.abs(h.vs_you))} ${h.vs_you > 0 ? 'above' : 'below'} your own moves · `)}
        {showScale && (p ? `Maia ${num(h.maia_level)} on the ${h.scale} scale, translated with your games` : `Maia's native scale`)}
      </div>
    </div>
  )
}

export function ScaleNote({ ready, games, needed, beyond }: { ready: boolean; games: number; needed?: number; beyond?: 'low' | 'high' }) {
  if (ready) return null
  if (beyond)
    return (
      <p className="m-0 text-2xs text-faint">
        Your own moves sit {beyond === 'low' ? 'below' : 'above'} the range Maia covers, so gambit can't measure your personal scale yet. Levels stay on Maia's Lichess blitz scale.
      </p>
    )
  return (
    <p className="m-0 text-2xs text-faint">
      Levels show on Maia's Lichess blitz scale until gambit has measured your own: it needs {needed ?? 15} analysed rated games
      {games ? ` (${games} so far)` : ''}. Then every level is also given in your platform's numbers.
    </p>
  )
}
