import * as Plot from '@observablehq/plot'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Board } from '../components/Board'
import { PlotFigure, tok } from '../components/Plot'
import { Header, Notice, Section, Segmented, View } from '../components/ui'
import { brain } from '../lib/brain'
import { Line, arrow } from '../lib/chess'
import { PLATFORM, cap, date, num, pct, timeControl } from '../lib/format'
import { useEvent, useNow, useRpc } from '../lib/hooks'
import type { LabGames, LabReveal, LabView, RevealMove } from '../lib/types'

export function GameLab() {
  const [view, setView] = useState<LabView | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const open = (game_id: number) => {
    setErr(null)
    brain
      .call<LabView>('lab.open', { game_id })
      .then(setView)
      .catch((e: Error) => setErr(e.message))
  }
  if (view) return <Session initial={view} onLeave={() => setView(null)} />
  return <Landing onOpen={open} onOpened={setView} err={err} />
}

// ── Choosing a game ─────────────────────────────────────────────────────────────────────────────

function Landing({ onOpen, onOpened, err }: { onOpen: (id: number) => void; onOpened: (v: LabView) => void; err: string | null }) {
  const { data } = useRpc<LabGames>('lab.games', { limit: 40 }, ['import'])
  const [pgn, setPgn] = useState('')
  const [color, setColor] = useState<'white' | 'black'>('white')
  const [pasteErr, setPasteErr] = useState<string | null>(null)
  const openGame = data?.games.find((g) => g.id === data.open_game_id)

  const paste = (e: React.FormEvent) => {
    e.preventDefault()
    setPasteErr(null)
    brain
      .call<LabView>('lab.import_pgn', { pgn, color })
      .then(onOpened)
      .catch((x: Error) => setPasteErr(x.message))
  }

  return (
    <View>
      <Header
        eyebrow="Game Lab"
        title="Your analysis first."
        sub={`Pick a finished game. You annotate it and flag the 1–3 moments that decided it; only then does the engine open, with Maia's view of how players at your level and stronger would have played. ${data ? `Each post-mortem is ${data.timebox_min} minutes and ends with 1–3 lessons.` : ''}`}
      />
      {openGame && (
        <div className="card mb-10 flex items-center justify-between gap-6 px-6 py-5">
          <div>
            <div className="text-xs text-muted">In progress</div>
            <div className="mt-0.5 text-sm">
              Your post-mortem of the game against {openGame.opp_name ?? 'your opponent'}, {date(openGame.played_at)}
            </div>
          </div>
          <button className="btn btn-primary" onClick={() => onOpen(openGame.id)}>
            Continue
          </button>
        </div>
      )}
      {err && <Notice tone="bad">{err}</Notice>}

      <Section title="Recent games" className="mt-0">
        {data?.games.length ? (
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="text-left text-2xs text-faint">
                <th className="pb-2 font-normal">Date</th>
                <th className="pb-2 font-normal">Game</th>
                <th className="pb-2 font-normal">Opponent</th>
                <th className="pb-2 font-normal">Result</th>
                <th className="pb-2 text-right font-normal">Post-mortem</th>
              </tr>
            </thead>
            <tbody>
              {data.games.map((g) => (
                <tr key={g.id} tabIndex={0} onClick={() => onOpen(g.id)} onKeyDown={(e) => e.key === 'Enter' && onOpen(g.id)} className="h-10 border-t hairline transition-colors hover:bg-[var(--hover)]">
                  <td className="tabular pr-4 text-muted">{date(g.played_at)}</td>
                  <td className="pr-4 whitespace-nowrap">
                    {cap(g.time_class)} <span className="tabular text-faint">{timeControl(g.time_control)}</span>
                    <span className="text-faint"> · {g.platform === 'pgn' ? 'pasted' : PLATFORM[g.platform]}</span>
                  </td>
                  <td className="max-w-[200px] truncate pr-4">
                    {g.opp_name ?? 'Unknown'} <span className="tabular text-faint">{g.opp_rating ?? ''}</span>
                  </td>
                  <td className="pr-4">{cap(g.result)}</td>
                  <td className="text-right text-muted">{g.closed_at ? 'Filed' : g.session_id ? 'In progress' : '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="m-0 text-xs text-muted">Imported games appear here. Until then, paste one below.</p>
        )}
      </Section>

      <Section title="Paste a game" note="Over-the-board games, or games from anywhere else">
        <form onSubmit={paste} className="grid gap-3">
          <textarea className="field font-mono text-xs" rows={6} value={pgn} onChange={(e) => setPgn(e.target.value)} placeholder={'[Event "Club night"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 …'} spellCheck={false} />
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 text-xs text-muted">
              You played
              <Segmented label="Your colour" value={color} options={[{ value: 'white', label: 'White' }, { value: 'black', label: 'Black' }]} onChange={setColor} />
            </div>
            <button className="btn" disabled={!pgn.trim()}>
              Open post-mortem
            </button>
          </div>
          {pasteErr && <Notice tone="bad">{pasteErr}</Notice>}
        </form>
      </Section>
    </View>
  )
}

// ── A post-mortem ───────────────────────────────────────────────────────────────────────────────

const MARK: Record<string, string> = { blunder: '??', mistake: '?', inaccuracy: '?!' }

function Session({ initial, onLeave }: { initial: LabView; onLeave: () => void }) {
  const [v, setV] = useState(initial)
  const [ply, setPly] = useState(0) // position after this many moves
  const [err, setErr] = useState<string | null>(null)
  const progress = useEvent<{ stage: string; done: number; total: number }>('lab')
  const [unlocking, setUnlocking] = useState(false)
  const now = useNow(15_000)
  const g = v.game
  const r = v.reveal
  const state = v.session.state
  const line = useMemo(() => new Line(g.start_fen, g.moves.map((m) => m.uci)), [g])

  const call = useCallback(
    (method: string, params: Record<string, unknown>) =>
      brain
        .call<LabView>(method, { session_id: v.session.id, ...params })
        .then((nv) => {
          setV(nv)
          setErr(null)
          return nv
        })
        .catch((e: Error) => {
          setErr(e.message)
          return null
        }),
    [v.session.id],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === 'TEXTAREA' || (e.target as HTMLElement)?.tagName === 'INPUT') return
      if (e.key === 'ArrowLeft') setPly((p) => Math.max(0, p - 1))
      else if (e.key === 'ArrowRight') setPly((p) => Math.min(g.moves.length, p + 1))
      else if (e.key === 'Home') setPly(0)
      else if (e.key === 'End') setPly(g.moves.length)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [g.moves.length])

  const unlock = () => {
    setUnlocking(true)
    call('lab.unlock', {}).finally(() => setUnlocking(false))
  }

  const board = useMemo(() => {
    const view = line.view(ply)
    const shapes = []
    const rm = r && ply > 0 ? r.moves[ply - 1] : null
    if (rm?.best_uci && rm.best_uci !== rm.uci && rm.color === g.my_color) {
      shapes.push(arrow(rm.uci, 'gold'), arrow(rm.best_uci, 'good'))
    }
    return { ...view, shapes }
  }, [line, ply, r, g.my_color])

  const elapsed = (now / 1000 - v.session.started_at) / 60
  const left = Math.max(0, Math.ceil(v.session.timebox_min - elapsed))
  const moment = v.moments.find((m) => m.ply === ply)
  const current = ply > 0 ? g.moves[ply - 1] : null

  return (
    <div className="grid h-full min-h-[640px] grid-cols-[1fr_400px]">
      <div className="grid place-items-center px-10 pt-12 pb-8" data-tauri-drag-region>
        <div className="aspect-square w-[min(calc(100vh-112px),100%)] rounded-[6px] bg-surface p-2.5 shadow-[0_0_0_1px_var(--line),0_30px_80px_-30px_rgb(0_0_0/0.8)]">
          <Board fen={board.fen} orientation={g.my_color} turnColor={board.turn} movable={null} dests={board.dests} lastMove={board.lastMove} check={board.check} shapes={board.shapes} />
        </div>
      </div>

      <aside className="flex min-h-0 flex-col gap-5 overflow-y-auto border-l hairline bg-surface px-7 pt-[52px] pb-6">
        <div className="flex items-baseline justify-between gap-4">
          <div className="eyebrow truncate">
            Game Lab <span className="text-faint normal-case tracking-normal">· {g.opp_name ?? 'opponent'} · {cap(g.result)}</span>
          </div>
          {state !== 'closed' && <div className={`tabular shrink-0 text-xs ${elapsed >= v.session.warn_min ? 'text-bad' : 'text-muted'}`}>{left} min left</div>}
        </div>

        <MoveList moves={g.moves} reveal={r} ply={ply} onPly={setPly} notes={v.notes} moments={v.moments.map((m) => m.ply)} myColor={g.my_color} />

        {state === 'annotate' && (
          <Annotate
            key={ply}
            ply={ply}
            san={current?.san}
            note={v.notes[String(ply)] ?? ''}
            moment={moment}
            momentCount={v.moments.length}
            max={v.session.max_moments}
            onNote={(text) => call('lab.note', { ply, text })}
            onMoment={(note, candidate) => call('lab.moment', { ply, note, candidate })}
            onRemove={() => call('lab.moment_remove', { ply })}
          />
        )}

        {(state === 'annotate' || (state === 'expired' && !v.session.unlocked)) && (
          <div className="grid gap-2 border-t hairline pt-5">
            <div className="text-xs text-muted">
              Critical moments <span className="tabular text-text">{v.moments.length}</span> of {v.session.max_moments}
              {state === 'expired' && ' · time is up, so the engine can open now'}
            </div>
            <button className="btn btn-primary justify-center" disabled={unlocking || (v.moments.length === 0 && state !== 'expired')} onClick={unlock}>
              {unlocking ? unlockLabel(progress) : 'Unlock the engine'}
            </button>
            {v.moments.length === 0 && state === 'annotate' && <span className="text-2xs text-faint">Flag at least one moment first: the move where you think the game turned.</span>}
          </div>
        )}

        {r && state !== 'closed' && <RevealPanel v={v} r={r} ply={ply} onPly={setPly} onEngine={(fen) => brain.call('lab.engine', { session_id: v.session.id, fen })} fen={board.fen} />}

        {(state === 'revealed' || (state === 'expired' && v.session.unlocked)) && (
          <Lessons max={v.session.max_lessons} onFile={(lessons) => call('lab.close', { lessons })} />
        )}

        {state === 'closed' && (
          <div className="grid gap-4">
            <h2 className="display m-0 text-lg">Filed and closed.</h2>
            <ol className="m-0 grid list-none gap-3 p-0">
              {v.lessons.map((l, i) => (
                <li key={i} className="grid grid-cols-[22px_1fr] font-serif text-md leading-snug font-light">
                  <span className="tabular text-faint">{i + 1}</span>
                  {l}
                </li>
              ))}
            </ol>
            <p className="m-0 text-2xs text-muted">Your critical positions from this game are now in Solve.</p>
          </div>
        )}

        {err && <Notice tone="bad">{err}</Notice>}
        <div className="mt-auto pt-2">
          <button className="btn btn-quiet -ml-3" onClick={onLeave}>
            ← All games
          </button>
        </div>
      </aside>
    </div>
  )
}

function unlockLabel(p: { stage: string; done: number; total: number } | null) {
  if (!p) return 'Opening the engine…'
  if (p.stage === 'maia') return 'Asking Maia…'
  return `Analysing ${p.stage === 'best moves' ? 'critical moments' : 'positions'} · ${p.done} of ${p.total}`
}

function MoveList({ moves, reveal, ply, onPly, notes, moments, myColor }: { moves: { ply: number; san: string }[]; reveal: LabReveal | null; ply: number; onPly: (p: number) => void; notes: Record<string, string>; moments: number[]; myColor: string }) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    box.current?.querySelector('[data-active]')?.scrollIntoView({ block: 'nearest' })
  }, [ply])
  const rows = []
  for (let i = 0; i < moves.length; i += 2) rows.push([moves[i], moves[i + 1]])
  const cell = (m?: { ply: number; san: string }) => {
    if (!m) return <span />
    const rm = reveal?.moves[m.ply - 1]
    const mine = rm && rm.color === myColor
    const mark = rm && MARK[rm.class]
    return (
      <button
        onClick={() => onPly(m.ply)}
        data-active={ply === m.ply ? '' : undefined}
        className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-left transition-colors ${ply === m.ply ? 'bg-[var(--active)] text-text' : 'hover:bg-[var(--hover)]'}`}
        aria-label={`${m.san}${moments.includes(m.ply) ? ', flagged as critical' : ''}`}
      >
        {m.san}
        {mark && <span className={mine ? 'text-bad' : 'text-faint'}>{mark}</span>}
        {moments.includes(m.ply) && <span className="text-[9px] text-text">◆</span>}
        {notes[String(m.ply)] && <span className="size-1 rounded-full bg-[var(--muted)]" />}
      </button>
    )
  }
  return (
    <div ref={box} className="max-h-[240px] min-h-[120px] shrink-0 overflow-y-auto font-mono text-xs">
      <div className="grid grid-cols-[28px_1fr_1fr] gap-y-0.5">
        {rows.map(([w, b], i) => (
          <div key={i} className="contents">
            <span className="tabular py-0.5 text-faint">{i + 1}</span>
            {cell(w)}
            {cell(b)}
          </div>
        ))}
      </div>
      <p className="mt-2 mb-0 font-sans text-2xs text-faint">← → to step through · ◆ critical moment</p>
    </div>
  )
}

function Annotate({ ply, san, note, moment, momentCount, max, onNote, onMoment, onRemove }: { ply: number; san?: string; note: string; moment?: { note: string; candidate: string | null }; momentCount: number; max: number; onNote: (t: string) => void; onMoment: (note: string, candidate: string) => void; onRemove: () => void }) {
  const [text, setText] = useState(note)
  const [flagging, setFlagging] = useState(!!moment)
  const [mNote, setMNote] = useState(moment?.note ?? '')
  const [cand, setCand] = useState(moment?.candidate ?? '')
  if (ply === 0) return <p className="m-0 text-xs text-muted">Step to a move to comment on it or flag it as a critical moment.</p>
  return (
    <div className="grid gap-4 border-t hairline pt-5">
      <label className="grid gap-1.5">
        <span className="text-xs text-muted">
          Your comment on <span className="font-mono text-text">{san}</span>
        </span>
        <textarea className="field text-xs" rows={2} value={text} onChange={(e) => setText(e.target.value)} onBlur={() => text !== note && onNote(text)} placeholder="What were you thinking? What did you fear?" />
      </label>
      {!flagging ? (
        <button className="btn justify-self-start" disabled={momentCount >= max} onClick={() => setFlagging(true)}>
          {momentCount >= max ? `${max} moments flagged` : 'Flag as a critical moment'}
        </button>
      ) : (
        <div className="grid gap-3 rounded-lg border hairline p-4">
          <div className="text-xs text-text">Critical moment</div>
          <textarea className="field text-xs" rows={2} value={mNote} onChange={(e) => setMNote(e.target.value)} placeholder="Why this move decided the game" autoFocus />
          <input className="field font-mono text-xs" value={cand} onChange={(e) => setCand(e.target.value)} placeholder="What you'd play now (optional), e.g. Nf3" spellCheck={false} />
          <div className="flex justify-between">
            <button
              className="btn btn-quiet -ml-3"
              onClick={() => {
                if (moment) onRemove()
                setFlagging(false)
              }}
            >
              {moment ? 'Remove' : 'Cancel'}
            </button>
            <button className="btn" disabled={!mNote.trim()} onClick={() => onMoment(mNote, cand)}>
              {moment ? 'Update moment' : 'Save moment'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function RevealPanel({ v, r, ply, onPly, onEngine, fen }: { v: LabView; r: LabReveal; ply: number; onPly: (p: number) => void; onEngine: (fen: string) => Promise<unknown>; fen: string }) {
  const g = v.game
  const maia = r.maia && !('error' in r.maia && r.maia.error) ? (r.maia as Exclude<LabReveal['maia'], { error: string } | null>) : null
  const moments = [...new Set([...r.engine_moments, ...r.your_moments])].sort((a, b) => a - b)
  const [check, setCheck] = useState<{ fen: string; cp: number | null; mate: number | null; line: string[]; checks: number; nudge: boolean } | null>(null)
  const [checkErr, setCheckErr] = useState<string | null>(null)
  const ask = () => {
    setCheckErr(null)
    onEngine(fen)
      .then((c) => setCheck({ ...(c as object as { cp: number | null; mate: number | null; line: string[]; checks: number; nudge: boolean }), fen }))
      .catch((e: Error) => setCheckErr(e.message))
  }
  const evalText = (c: { cp: number | null; mate: number | null }) => (c.mate != null ? `Mate in ${Math.abs(c.mate)} for ${c.mate > 0 ? 'White' : 'Black'}` : `${(c.cp! / 100 > 0 ? '+' : '') + (c.cp! / 100).toFixed(2)}`)
  return (
    <div className="grid gap-6 border-t hairline pt-5">
      <div>
        <h2 className="display m-0 text-lg">
          You found {r.found.length} of {r.engine_moments.length} moment{r.engine_moments.length === 1 ? '' : 's'} the engine picked.
        </h2>
        <p className="mt-1.5 mb-0 text-2xs text-muted">Click a moment to see it. Gold is your move, green the engine's.</p>
      </div>

      <EvalChart r={r} ply={ply} myColor={g.my_color} />

      <div className="grid gap-3">
        {moments.map((p) => {
          const m = r.moves[p - 1]
          const yours = v.moments.find((x) => x.ply === p)
          const mm = maia?.moves.find((x) => x.ply === p)
          return (
            <button key={p} onClick={() => onPly(p)} className={`grid gap-1.5 rounded-lg border p-3.5 text-left text-xs transition-colors ${ply === p ? 'border-[var(--text)]' : 'hairline hover:bg-[var(--hover)]'}`}>
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-mono text-sm">
                  {Math.ceil(p / 2)}
                  {p % 2 ? '.' : '…'} {m.san}
                  {MARK[m.class] && <span className="text-bad"> {MARK[m.class]}</span>}
                </span>
                <span className="text-2xs text-faint">{r.engine_moments.includes(p) && yours ? 'you both flagged it' : yours ? 'your pick' : 'engine’s pick'}</span>
              </div>
              {yours && <span className="text-muted">You: {yours.note}{yours.candidate ? ` (you’d play ${yours.candidate})` : ''}</span>}
              {m.best_san && m.best_uci !== m.uci && (
                <span>
                  Engine: <span className="font-mono">{m.best_line?.join(' ') ?? m.best_san}</span> <span className="text-faint">· cost {(m.cp_loss / 100).toFixed(1)} pawns</span>
                </span>
              )}
              {m.best_uci === m.uci && <span className="text-good">The engine agrees with your move.</span>}
              {mm && maia && (
                <span className="text-muted">
                  Maia {num(maia.self_level)} plays {mm.top_self ?? '–'} ({pct(mm.p_self)} for yours) · Maia {num(maia.high_level)} plays {mm.top_high ?? '–'} ({pct(mm.p_high)})
                </span>
              )}
            </button>
          )
        })}
        {moments.length === 0 && <p className="m-0 text-xs text-muted">No costly errors of yours in this game.</p>}
      </div>

      {maia?.fit && (
        <div className="text-xs text-muted">
          Your moves in this game looked most like a <span className="tabular text-text">{num(maia.fit.level)}</span> player’s, by Maia. A resemblance across {maia.fit.moves} moves, not a rating.
        </div>
      )}
      {r.maia && 'error' in r.maia && r.maia.error && <Notice>Maia couldn’t run for this game, so only the engine’s view is shown.</Notice>}

      <TimeChart r={r} />

      <div className="grid gap-2 border-t hairline pt-5">
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-muted">This position, checked by Stockfish</span>
          <button className="btn" onClick={ask}>
            Check
          </button>
        </div>
        {check && check.fen === fen && (
          <div className="grid gap-1 text-xs">
            <span>
              <span className="tabular font-mono">{evalText(check)}</span> <span className="font-mono text-muted">{check.line.join(' ')}</span>
            </span>
            {check.nudge && <Notice>That’s check number {check.checks} of this position. The answer won’t change; put what you learned into a lesson instead.</Notice>}
          </div>
        )}
        {checkErr && <Notice tone="bad">{checkErr}</Notice>}
      </div>
    </div>
  )
}

function EvalChart({ r, ply, myColor }: { r: LabReveal; ply: number; myColor: string }) {
  const data = useMemo(() => r.evals.map((cp, i) => ({ i, pawns: Math.max(-6, Math.min(6, cp / 100)) })), [r.evals])
  const errors = useMemo(
    () => r.moves.filter((m: RevealMove) => m.color === myColor && (m.class === 'mistake' || m.class === 'blunder')).map((m) => ({ i: m.ply, pawns: data[m.ply]?.pawns ?? 0 })),
    [r.moves, myColor, data],
  )
  const make = useCallback(
    (): Plot.PlotOptions => ({
      marginLeft: 28,
      marginRight: 8,
      marginBottom: 18,
      marginTop: 6,
      x: { label: null, ticks: 4, tickFormat: (d: number) => (d ? String(Math.ceil(d / 2)) : '') },
      y: { label: null, domain: [-6, 6], ticks: 3, tickFormat: (d: number) => (d > 0 ? `+${d}` : String(d)) },
      style: { color: tok('muted') },
      marks: [
        Plot.ruleY([0], { stroke: tok('line') }),
        Plot.areaY(data, { x: 'i', y: 'pawns', fill: tok('text'), fillOpacity: 0.08, curve: 'monotone-x' }),
        Plot.lineY(data, { x: 'i', y: 'pawns', stroke: tok('text'), strokeWidth: 1.5, curve: 'monotone-x' }),
        Plot.ruleX([ply], { stroke: tok('gold'), strokeOpacity: 0.7 }),
        Plot.dot(errors, { x: 'i', y: 'pawns', r: 4, fill: tok('bad'), stroke: tok('surface'), strokeWidth: 2 }),
        Plot.tip(data, Plot.pointerX({ x: 'i', y: 'pawns', title: (d: { i: number; pawns: number }) => `Move ${Math.ceil(d.i / 2) || 0}\n${d.pawns > 0 ? '+' : ''}${d.pawns.toFixed(1)} for White` })),
      ],
    }),
    [data, errors, ply],
  )
  return (
    <figure className="m-0">
      <PlotFigure make={make} height={110} label="Evaluation through the game, White's point of view" />
      <figcaption className="mt-1 text-2xs text-faint">Evaluation in pawns for White · red dots are your errors</figcaption>
    </figure>
  )
}

function TimeChart({ r }: { r: LabReveal }) {
  const rows = useMemo(() => r.time.moves.filter((t) => t.spent_s != null).map((t) => ({ ...t, move: Math.ceil(t.ply / 2) })), [r.time.moves])
  const make = useCallback(
    (): Plot.PlotOptions => ({
      marginLeft: 28,
      marginRight: 8,
      marginBottom: 18,
      marginTop: 6,
      x: { label: null, ticks: 4 },
      y: { label: null, ticks: 3, tickFormat: (d: number) => `${d}s` },
      style: { color: tok('muted') },
      marks: [
        Plot.ruleY([0], { stroke: tok('line') }),
        Plot.rectY(rows, { x1: (d: { move: number }) => d.move - 0.4, x2: (d: { move: number }) => d.move + 0.4, y: 'spent_s', fill: (d: { critical: boolean }) => (d.critical ? tok('bad') : tok('muted')), fillOpacity: (d: { critical: boolean }) => (d.critical ? 0.9 : 0.45), rx: 2 }),
        Plot.tip(rows, Plot.pointerX({ x: 'move', y: 'spent_s', title: (d: { move: number; spent_s: number; critical: boolean }) => `Move ${d.move}: ${d.spent_s}s${d.critical ? '\nA lot was at stake' : ''}` })),
      ],
    }),
    [rows],
  )
  if (rows.length < 3) return null
  return (
    <figure className="m-0">
      <div className="mb-1 text-xs text-muted">Where your time went</div>
      <PlotFigure make={make} height={100} label="Seconds spent per move, critical moves highlighted" />
      <figcaption className="mt-1 text-2xs text-faint">
        Moves where a lot was at stake (red) were {pct(r.time.critical_share_of_moves)} of your moves and got {pct(r.time.critical_share_of_time)} of your time.
      </figcaption>
    </figure>
  )
}

function Lessons({ max, onFile }: { max: number; onFile: (l: string[]) => void }) {
  const [lessons, setLessons] = useState<string[]>(Array(max).fill(''))
  const filled = lessons.filter((l) => l.trim()).length
  return (
    <form
      className="grid gap-3 border-t hairline pt-5"
      onSubmit={(e) => {
        e.preventDefault()
        onFile(lessons)
      }}
    >
      <div className="text-xs text-muted">Lessons · 1 to {max}, then the file closes</div>
      {lessons.map((l, i) => (
        <textarea key={i} className="field text-xs" rows={2} value={l} onChange={(e) => setLessons((ls) => ls.map((x, j) => (j === i ? e.target.value : x)))} placeholder={i === 0 ? 'What will you do differently next time?' : ''} />
      ))}
      <button className="btn btn-primary justify-self-end" disabled={!filled}>
        File and close
      </button>
    </form>
  )
}
