import { useState } from 'react'
import { brain } from '../lib/brain'
import { PLATFORM, cap, date, dateLong, duration, num, timeControl } from '../lib/format'
import { useRpc } from '../lib/hooks'
import { openExternal } from '../lib/native'
import type { AnalysisStatus, GameRow, ImportState, MirrorSummary, Settings } from '../lib/types'
import { Header, Notice, Progress, Section, View } from '../components/ui'

export function Mirror({
  settings,
  analysis,
  imp,
  onSettingsChange,
}: {
  settings: Settings | null
  analysis: AnalysisStatus | null
  imp: ImportState | null
  onSettingsChange: (s: Settings) => void
}) {
  const { data, error } = useRpc<MirrorSummary>('mirror.summary', { limit: 60 }, ['import', 'analysis'])
  const hasAccount = !!(settings?.chesscom_username || settings?.lichess_username)

  if (settings && !hasAccount) return <Onboarding onSaved={onSettingsChange} />
  if (!data)
    return (
      <View>
        <Header eyebrow="Mirror" title={<span className="text-faint">Reading your games…</span>} />
        {error && <Notice tone="bad">{error}</Notice>}
      </View>
    )

  const t = data.totals
  const a = analysis ?? data.analysis
  const im = imp ?? data.import
  const accounts = [
    t.chesscom ? `${PLATFORM.chesscom} ${num(t.chesscom)}` : null,
    t.lichess ? `${PLATFORM.lichess} ${num(t.lichess)}` : null,
  ].filter(Boolean)

  return (
    <View>
      <Header
        eyebrow="Mirror"
        title={
          t.games ? (
            <>
              <span className="tabular">{num(t.games)}</span> games
            </>
          ) : (
            'No games yet'
          )
        }
        sub={t.games ? `${accounts.join(' · ')} · ${dateLong(t.first!)} to ${dateLong(t.last!)}` : 'Import your history to begin.'}
      />

      <div className="card grid divide-y divide-[var(--line)]">
        <ImportRow imp={im} settings={settings} />
        <AnalysisRow a={a} locked={settings?.fairplay_lock ?? false} />
      </div>

      <div className="mt-5">
        <Notice>
          Mirror shows where your errors happened, never what the right move was. Those positions become your Solve sets, so the answers stay
          hidden until you've tried them.
        </Notice>
      </div>

      <Section title="Recent games" note={data.recent.length ? `Latest ${data.recent.length}` : undefined}>
        {data.recent.length ? <GamesTable rows={data.recent} /> : <p className="m-0 text-xs text-muted">Games appear here as they import.</p>}
      </Section>
    </View>
  )
}

function ImportRow({ imp, settings }: { imp: ImportState; settings: Settings | null }) {
  const [err, setErr] = useState<string | null>(null)
  const running = imp.state === 'running'
  const start = () => {
    setErr(null)
    brain.call('import.start').catch((e: Error) => setErr(e.message))
  }
  let line: string
  if (running) {
    const where = imp.platform ? PLATFORM[imp.platform] : 'your accounts'
    const step = imp.step && imp.step !== 'streaming' && imp.step !== 'done' ? ` · ${imp.step}` : ''
    line = `Fetching ${where}${step} · ${num(imp.stored ?? 0)} new`
  } else if (imp.state === 'done') {
    line = imp.stored ? `${num(imp.stored)} new games imported` : 'Up to date'
  } else if (imp.state === 'error') {
    line = 'Import stopped'
  } else {
    const names = [settings?.chesscom_username && `${settings.chesscom_username} on Chess.com`, settings?.lichess_username && `${settings.lichess_username} on Lichess`]
    line = `Ready to fetch ${names.filter(Boolean).join(' and ')}`
  }
  const progress = running && imp.total ? (imp.done ?? 0) / imp.total : null
  return (
    <div className="grid gap-3 px-6 py-5">
      <div className="flex items-center justify-between gap-6">
        <div className="min-w-0">
          <div className="text-xs text-muted">Import</div>
          <div className="mt-0.5 truncate text-sm">{line}</div>
        </div>
        <button className="btn" onClick={start} disabled={running}>
          {running ? 'Importing…' : 'Check for new games'}
        </button>
      </div>
      {progress != null && <Progress value={progress} />}
      {[...(imp.errors ?? []), ...(err ? [err] : [])].map((e) => (
        <Notice key={e} tone="bad">
          {e}
        </Notice>
      ))}
    </div>
  )
}

function AnalysisRow({ a, locked }: { a: AnalysisStatus; locked: boolean }) {
  const [err, setErr] = useState<string | null>(null)
  const call = (m: string) => {
    setErr(null)
    brain.call(m).catch((e: Error) => setErr(e.message))
  }
  const active = a.state === 'running' || a.state === 'pausing'
  const deep = a.phase === 'deep' || (a.analysed === a.games && a.deep < a.games)
  const pending = a.games - a.analysed
  let line: string
  if (!a.games) line = 'Nothing to analyse yet'
  else if (locked && a.deep < a.games) line = 'Stopped by the fair-play lock'
  else if (a.state === 'error') line = 'Analysis stopped with an error'
  else if (a.state === 'pausing') line = 'Pausing after the positions in flight'
  else if (active && !deep) line = `${num(a.analysed)} of ${num(a.games)} games analysed`
  else if (active && deep) line = `Re-checking blunders at depth · ${num(a.deep)} of ${num(a.games)}`
  else if (pending > 0) line = `${num(pending)} games waiting`
  else if (a.deep < a.games) line = `First pass done · ${num(a.games - a.deep)} games to re-check`
  else line = 'Every game analysed'

  const detail =
    active && a.positions_per_s
      ? `${a.positions_per_s} positions a second${a.eta_s ? ` · about ${duration(a.eta_s)} left` : ''}`
      : active
        ? 'Starting Stockfish…'
        : null
  const done = deep ? a.deep : a.analysed
  return (
    <div className="grid gap-3 px-6 py-5">
      <div className="flex items-center justify-between gap-6">
        <div className="min-w-0">
          <div className="text-xs text-muted">Analysis</div>
          <div className="mt-0.5 truncate text-sm">{line}</div>
          {detail && <div className="tabular mt-0.5 text-2xs text-faint">{detail}</div>}
        </div>
        {a.games > 0 && !locked && (
          active ? (
            <button className="btn" onClick={() => call('analysis.pause')} disabled={a.state === 'pausing'}>
              Pause
            </button>
          ) : (
            a.deep < a.games && (
              <button className="btn" onClick={() => call('analysis.start')}>
                {a.analysed || a.state === 'paused' ? 'Resume analysis' : 'Analyse games'}
              </button>
            )
          )
        )}
      </div>
      {a.games > 0 && (active || a.state === 'paused') && <Progress value={done / a.games} />}
      {(a.error || err) && <Notice tone="bad">{err ?? a.error}</Notice>}
    </div>
  )
}

function GamesTable({ rows }: { rows: GameRow[] }) {
  return (
    <table className="w-full border-collapse text-xs">
      <thead>
        <tr className="text-left text-2xs text-faint">
          <th className="pb-2 font-normal">Date</th>
          <th className="pb-2 font-normal">Game</th>
          <th className="pb-2 font-normal">Opponent</th>
          <th className="pb-2 font-normal">Result</th>
          <th className="pb-2 font-normal">Opening</th>
          <th className="pb-2 text-right font-normal">Errors</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((g) => (
          <tr
            key={g.id}
            tabIndex={g.url ? 0 : -1}
            onClick={() => g.url && openExternal(g.url)}
            onKeyDown={(e) => e.key === 'Enter' && g.url && openExternal(g.url)}
            className="h-10 border-t hairline transition-colors duration-150 hover:bg-[var(--hover)]"
            title={g.url ? `Open on ${PLATFORM[g.platform]}` : undefined}
          >
            <td className="tabular pr-4 text-muted">{date(g.played_at)}</td>
            <td className="pr-4 whitespace-nowrap">
              <span className={`mr-2 inline-block size-2 rounded-full border border-[var(--muted)] align-[1px] ${g.my_color === 'white' ? 'bg-[var(--text)]' : 'bg-transparent'}`} aria-label={`You played ${g.my_color}`} />
              {cap(g.time_class)} <span className="tabular text-faint">{timeControl(g.time_control)}</span>
              {!g.rated && <span className="ml-1.5 text-faint">casual</span>}
            </td>
            <td className="max-w-[180px] truncate pr-4">
              {g.opp_name ?? 'Unknown'} <span className="tabular text-faint">{g.opp_rating ?? ''}</span>
            </td>
            <td className="pr-4 whitespace-nowrap">
              <span className={g.result === 'win' ? 'text-text' : g.result === 'loss' ? 'text-muted' : 'text-muted'}>{cap(g.result)}</span>
              {g.termination && <span className="text-faint"> · {g.termination.replace('_', ' ')}</span>}
            </td>
            <td className="max-w-[240px] truncate pr-4 text-muted">{g.opening ?? '–'}</td>
            <td className="text-right whitespace-nowrap">
              <ErrorMarks g={g} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Blunders as filled marks, mistakes as hollow ones; counts in the tooltip and accessible label. */
function ErrorMarks({ g }: { g: GameRow }) {
  if (!g.analysed) return <span className="text-faint">pending</span>
  if (!g.blunders && !g.mistakes) return <span className="text-faint">clean</span>
  const label = `${g.blunders} blunder${g.blunders === 1 ? '' : 's'}, ${g.mistakes} mistake${g.mistakes === 1 ? '' : 's'}`
  const marks = (n: number, cls: string) => Array.from({ length: Math.min(n, 6) }, (_, i) => <span key={i} className={`inline-block size-[7px] rounded-full ${cls}`} />)
  return (
    <span className="inline-flex items-center gap-[3px]" title={label} aria-label={label}>
      {marks(g.blunders, 'bg-[var(--bad)]')}
      {marks(g.mistakes, 'border border-[var(--muted)]')}
    </span>
  )
}

function Onboarding({ onSaved }: { onSaved: (s: Settings) => void }) {
  const [chesscom, setChesscom] = useState('')
  const [lichess, setLichess] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!chesscom.trim() && !lichess.trim()) return setErr('Enter at least one username.')
    setBusy(true)
    setErr(null)
    try {
      const s = await brain.call<Settings>('settings.set', { chesscom_username: chesscom.trim(), lichess_username: lichess.trim() })
      onSaved(s)
      await brain.call('import.start')
    } catch (e) {
      setErr((e as Error).message)
      setBusy(false)
    }
  }
  return (
    <View>
      <div className="mx-auto max-w-[520px] pt-[8vh]">
        <div className="eyebrow mb-3">Mirror</div>
        <h1 className="display m-0 text-2xl">Bring your games in.</h1>
        <p className="mt-4 mb-10 text-sm text-muted">
          gambit fetches every game you've played, then has Stockfish read each move overnight and marks where the big errors happened. Your games stay
          on this Mac.
        </p>
        <form onSubmit={submit} className="grid gap-5">
          <label className="grid gap-1.5">
            <span className="text-xs text-muted">Chess.com username</span>
            <input className="field" value={chesscom} onChange={(e) => setChesscom(e.target.value)} autoFocus autoComplete="off" spellCheck={false} />
          </label>
          <label className="grid gap-1.5">
            <span className="text-xs text-muted">Lichess username</span>
            <input className="field" value={lichess} onChange={(e) => setLichess(e.target.value)} autoComplete="off" spellCheck={false} />
          </label>
          {err && <Notice tone="bad">{err}</Notice>}
          <div className="mt-2 flex items-center justify-between gap-4">
            <span className="text-2xs text-faint">Lichess imports run faster with a token. Add one later in Settings.</span>
            <button className="btn btn-primary" disabled={busy}>
              {busy ? 'Starting…' : 'Import games'}
            </button>
          </div>
        </form>
      </div>
    </View>
  )
}
