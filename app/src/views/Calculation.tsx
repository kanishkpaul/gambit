import { useEffect, useMemo, useState } from 'react'
import { Board } from '../components/Board'
import { Figure, Header, Notice, Segmented, View } from '../components/ui'
import { brain } from '../lib/brain'
import { Line, arrow, uciFromSan } from '../lib/chess'
import { num, pct, themeWords, visibleThemes } from '../lib/format'
import { useNow, useRpc } from '../lib/hooks'
import type { CalcOverview, CalcPosition, CalcResult } from '../lib/types'

const EMPTY = '8/8/8/8/8/8/8/8 w - - 0 1'
const pawns = (cp: number) => (Math.abs(cp) >= 1000 ? (cp > 0 ? 'winning (mate)' : 'losing (mate)') : `${cp > 0 ? '+' : ''}${(cp / 100).toFixed(1)}`)

export function Calculation() {
  const { data: ov, reload } = useRpc<CalcOverview>('calc.overview')
  const [mode, setMode] = useState<'board' | 'visual'>('board')
  const [pos, setPos] = useState<CalcPosition | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const start = () => {
    setErr(null)
    brain
      .call<CalcPosition>('calc.next', { mode })
      .then(setPos)
      .catch((e: Error) => setErr(e.message))
  }
  if (pos) return <Practice key={pos.puzzle_id} p={pos} onNext={start} onLeave={() => (setPos(null), reload())} />
  return (
    <View>
      <Header
        eyebrow="Calculation"
        title="Think it through before you touch a piece."
        sub="The pieces stay frozen. List your candidate moves, write the line you believe, take one deliberate look at another part of the board, and only then let the engine check it."
      />
      <div className="grid grid-cols-4 gap-6 border-y hairline py-6">
        <Figure label="Positions calculated" value={num(ov?.attempts ?? 0)} />
        <Figure label="First move right" value={pct(ov?.first_correct)} />
        <Figure label="Saw it, chose otherwise" value={pct(ov?.saw_but_rejected)} note="the answer was among your candidates" />
        <Figure label="Line depth matched" value={ov?.avg_plies_matched != null ? ov.avg_plies_matched.toFixed(1) : '–'} note="half-moves, on average" />
      </div>
      <div className="mt-8 flex items-center gap-4">
        <Segmented label="Mode" value={mode} options={[{ value: 'board', label: 'Board' }, { value: 'visual', label: 'Visualization' }]} onChange={setMode} />
        <button className="btn btn-primary" onClick={start} disabled={ov ? !ov.library_ready : true}>
          Start
        </button>
        <span className="text-2xs text-muted">
          {mode === 'visual' ? `The pieces vanish after ${ov?.visual_seconds ?? 12} seconds; you calculate from memory.` : 'Long-solution positions near your level.'}
        </span>
      </div>
      {ov && !ov.library_ready && (
        <div className="mt-4">
          <Notice>Import the puzzle library in Solve first; calculation positions come from it.</Notice>
        </div>
      )}
      {err && (
        <div className="mt-4">
          <Notice tone="bad">{err}</Notice>
        </div>
      )}
    </View>
  )
}

type Step = 'candidates' | 'line' | 'scan' | 'checking' | 'result'

function Practice({ p, onNext, onLeave }: { p: CalcPosition; onNext: () => void; onLeave: () => void }) {
  const [step, setStep] = useState<Step>('candidates')
  const [cands, setCands] = useState(['', '', '', ''])
  const [line, setLine] = useState('')
  const [scan, setScan] = useState('')
  const [res, setRes] = useState<CalcResult | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [ply, setPly] = useState(0)
  const [which, setWhich] = useState<'best' | 'yours'>('best')
  const now = useNow(250)
  const [shownAt] = useState(() => Date.now())
  const lead = useMemo(() => new Line(p.start_fen, [p.lead_uci]), [p])
  const [ledIn, setLedIn] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setLedIn(true), 500)
    return () => clearTimeout(t)
  }, [])
  const hidden = p.mode === 'visual' && step !== 'result' && (now - shownAt) / 1000 > p.visual_seconds
  const pos = useMemo(() => new Line(p.fen).pos(), [p.fen])

  const candidateErrors = cands.map((c) => (c.trim() && !uciFromSan(pos, c) ? 'not legal here' : null))

  const submit = () => {
    setStep('checking')
    setErr(null)
    brain
      .call<CalcResult>('calc.submit', { puzzle_id: p.puzzle_id, candidates: cands.filter((c) => c.trim()), line, scan_note: scan || null })
      .then((r) => {
        setRes(r)
        setPly(0)
        setStep('result')
      })
      .catch((e: Error) => {
        setErr(e.message)
        setStep('line')
      })
  }

  const board = useMemo(() => {
    if (res) {
      const l = new Line(res.fen, which === 'best' ? res.best_ucis : res.your_ucis)
      const v = l.view(ply)
      const shapes = ply === 0 ? [arrow(res.best_ucis[0], 'good'), ...(res.your_ucis[0] !== res.best_ucis[0] ? [arrow(res.your_ucis[0], 'gold')] : [])] : []
      return { ...v, shapes }
    }
    const v = ledIn ? lead.view() : lead.view(0)
    return { ...v, fen: hidden ? EMPTY : v.fen, shapes: [] }
  }, [res, which, ply, ledIn, lead, hidden])

  useEffect(() => {
    if (!res) return
    const len = (which === 'best' ? res.best_ucis : res.your_ucis).length
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === 'INPUT' || (e.target as HTMLElement)?.tagName === 'TEXTAREA') return
      if (e.key === 'ArrowRight') setPly((x) => Math.min(len, x + 1))
      if (e.key === 'ArrowLeft') setPly((x) => Math.max(0, x - 1))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [res, which])

  return (
    <div className="grid h-full min-h-[640px] grid-cols-[1fr_380px]">
      <div className="grid place-items-center px-10 pt-12 pb-8" data-tauri-drag-region>
        <div className="aspect-square w-[min(calc(100vh-112px),100%)] rounded-[6px] bg-surface p-2.5 shadow-[0_0_0_0.5px_var(--line),0_12px_32px_-12px_rgb(0_0_0/0.35)]">
          <Board fen={board.fen} orientation={p.turn} turnColor={board.turn} movable={null} dests={board.dests} lastMove={hidden ? undefined : board.lastMove} check={!hidden && board.check} shapes={board.shapes} />
        </div>
      </div>
      <aside className="flex min-h-0 flex-col gap-5 overflow-y-auto border-l hairline bg-surface px-7 pt-[52px] pb-6">
        <div className="flex items-baseline justify-between">
          <div className="eyebrow">Calculation · {p.mode === 'visual' ? 'visualization' : 'board'}</div>
          {p.mode === 'visual' && step !== 'result' && <div className="tabular text-xs text-muted">{hidden ? 'from memory' : `${Math.max(0, Math.ceil(p.visual_seconds - (now - shownAt) / 1000))} s`}</div>}
        </div>
        <h2 className="display m-0 text-xl">{p.turn === 'white' ? 'White' : 'Black'} to move.</h2>

        {(step === 'candidates' || step === 'line' || step === 'scan') && (
          <>
            <div className="grid gap-1.5">
              <span className="text-xs text-muted">1 · Candidate moves</span>
              <div className="grid grid-cols-2 gap-2">
                {cands.map((c, i) => (
                  <input key={i} className={`field font-mono text-sm ${candidateErrors[i] ? 'border-[var(--bad)]' : ''}`} value={c} onChange={(e) => setCands((cs) => cs.map((x, j) => (j === i ? e.target.value : x)))} placeholder={i === 0 ? 'e.g. Nxe5' : ''} spellCheck={false} autoComplete="off" disabled={step !== 'candidates'} />
                ))}
              </div>
              {step === 'candidates' && (
                <button className="btn justify-self-end" disabled={!cands.some((c) => c.trim()) || candidateErrors.some(Boolean)} onClick={() => setStep('line')}>
                  Next: your line
                </button>
              )}
            </div>
            {step !== 'candidates' && (
              <div className="grid gap-1.5">
                <span className="text-xs text-muted">2 · The line you believe, both sides</span>
                <textarea className="field font-mono text-sm" rows={3} value={line} onChange={(e) => setLine(e.target.value)} placeholder="Nxe5 dxe5 Qh5+ Kf8 Qxe5" spellCheck={false} disabled={step !== 'line'} autoFocus />
                {step === 'line' && (
                  <button className="btn justify-self-end" disabled={!line.trim()} onClick={() => setStep('scan')}>
                    Next: one more look
                  </button>
                )}
              </div>
            )}
            {step === 'scan' && (
              <div className="grid gap-1.5">
                <span className="text-xs text-muted">3 · Look once at a part of the board you haven’t considered</span>
                <p className="m-0 text-2xs text-faint">The other king, a loose piece, a back rank, a check you skipped. Anything new? Change your line above if so.</p>
                <textarea className="field text-xs" rows={2} value={scan} onChange={(e) => setScan(e.target.value)} placeholder="Nothing new, or what you noticed" />
                <div className="flex justify-between">
                  <button className="btn btn-quiet -ml-3" onClick={() => setStep('line')}>
                    Edit my line
                  </button>
                  <button className="btn btn-primary" onClick={submit}>
                    Check with the engine
                  </button>
                </div>
              </div>
            )}
          </>
        )}
        {step === 'checking' && <p className="m-0 text-sm text-muted">Stockfish is checking both lines…</p>}

        {res && step === 'result' && (
          <div className="grid gap-5">
            <h3 className={`display m-0 text-lg ${res.first_correct ? 'text-good' : ''}`}>
              {res.first_correct ? (res.plies_matched >= res.best_ucis.length ? 'Right, all the way.' : 'Right first move.') : res.saw_it ? 'You saw it, then chose another move.' : 'The key move wasn’t on your list.'}
            </h3>
            <div className="grid gap-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-muted">Compare</span>
                <Segmented label="Line" value={which} options={[{ value: 'best', label: 'Best line' }, { value: 'yours', label: 'Your line' }]} onChange={(v) => (setWhich(v), setPly(0))} />
              </div>
              <div className="font-mono text-sm">
                <span className="text-muted">Best:</span> {res.best_line.join(' ')} <span className="text-faint">→ {pawns(res.best_cp)}</span>
              </div>
              <div className="font-mono text-sm">
                <span className="text-muted">Yours:</span> {res.your_line.join(' ')} <span className="text-faint">→ {pawns(res.end_cp)}</span>
              </div>
              {res.stopped_at && <span className="text-2xs text-bad">Your line stopped at “{res.stopped_at}”, which isn’t legal there.</span>}
              <span className="text-2xs text-muted">
                {res.plies_matched} of {res.best_ucis.length} half-moves matched · step with ← → · {Math.round(res.ms / 1000)} s
              </span>
            </div>
            <div className="text-2xs text-muted">
              Lichess puzzle {num(res.rating)} · {visibleThemes(res.themes).map(themeWords).join(' · ')}
            </div>
            <button className="btn btn-primary justify-self-end" onClick={onNext} autoFocus>
              Next position
            </button>
          </div>
        )}
        {err && <Notice tone="bad">{err}</Notice>}
        <div className="mt-auto">
          <button className="btn btn-quiet -ml-3" onClick={onLeave}>
            ← Calculation
          </button>
        </div>
      </aside>
    </div>
  )
}
