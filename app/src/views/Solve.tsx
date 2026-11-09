import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Board } from '../components/Board'
import { Figure, Header, Notice, Progress, View } from '../components/ui'
import { brain } from '../lib/brain'
import { Line, arrow, uciFromBoard, uciFromSan } from '../lib/chess'
import { PLATFORM, date, dateLong, days, num, themeWords, visibleThemes } from '../lib/format'
import { useEvent, useNow, useRpc } from '../lib/hooks'
import { openExternal } from '../lib/native'
import type { CalibrationStatus, MoveResult, PuzzleLibrary, Reveal, SolveNext, SolveOverview, SolvePosition, SolveSummary } from '../lib/types'

type Mode = 'standard' | 'speed' | 'calibration'
type EndReason = 'timebox' | 'complete' | 'ended'
type Confidence = 'guess' | 'unsure' | 'sure'
const CONFIDENCE: { value: Confidence; label: string; key: string }[] = [
  { value: 'guess', label: 'Guess', key: '1' },
  { value: 'unsure', label: 'Unsure', key: '2' },
  { value: 'sure', label: 'Sure', key: '3' },
]

export function Solve() {
  const { data: ov, reload } = useRpc<SolveOverview>('solve.overview', {}, ['puzzles'])
  const [stage, setStage] = useState<'landing' | 'solving' | 'summary'>('landing')
  const [summary, setSummary] = useState<{ s: SolveSummary; reason: EndReason } | null>(null)
  const [err, setErr] = useState<string | null>(null)

  // A set already running in the brain (the window reloaded): pick it back up.
  useEffect(() => {
    if (ov?.session && stage === 'landing') setStage('solving')
  }, [ov?.session, stage])

  const start = (mode: Mode) => {
    setErr(null)
    brain
      .call('solve.start', { mode })
      .then(() => setStage('solving'))
      .catch((e: Error) => setErr(e.message))
  }
  const finish = (s: SolveSummary, reason: EndReason) => {
    setSummary({ s, reason })
    setStage('summary')
    reload()
  }

  if (stage === 'solving') return <Session onDone={finish} />
  if (stage === 'summary' && summary) return <Summary s={summary.s} reason={summary.reason} onBack={() => setStage('landing')} />
  return <Landing ov={ov} err={err} onStart={start} />
}

// ── Landing ──────────────────────────────────────────────────────────────────────────────────────

function Landing({ ov, err, onStart }: { ov: SolveOverview | null; err: string | null; onStart: (m: Mode) => void }) {
  const { data: libInitial } = useRpc<PuzzleLibrary>('puzzles.status')
  const lib = useEvent<PuzzleLibrary>('puzzles', libInitial)
  if (!ov || !lib)
    return (
      <View>
        <Header eyebrow="Solve" title={<span className="text-faint">Getting your set ready…</span>} />
      </View>
    )
  const canStart = ov.library > 0 || ov.new_own > 0 || ov.due > 0
  const title = ov.due > 0 ? `${num(ov.due)} position${ov.due === 1 ? ' is' : 's are'} due.` : canStart ? 'Nothing is due. Time for new positions.' : 'Nothing to solve yet.'
  return (
    <View>
      <Header
        eyebrow="Solve"
        title={title}
        sub="Each set mixes positions from your own games with library puzzles, unlabelled. You commit to a move, a line and how sure you are before anything is revealed."
      />

      <div className="grid grid-cols-4 gap-6 border-y hairline py-6">
        <Figure label="Due now" value={num(ov.due)} note={ov.due_later_today ? `${num(ov.due_later_today)} more later today` : 'reviews come first'} />
        <Figure label="From your games" value={num(ov.new_own)} note="new, with colour-flipped twins" />
        <Figure label="In rotation" value={num(ov.learning)} note="scheduled with FSRS" />
        <Figure label="Solving around" value={ov.rated_attempts ? num(ov.solve_rating) : '–'} note={ov.rated_attempts ? `Lichess puzzle scale · ${ov.rated_attempts} rated` : `starts at ${num(ov.solve_rating)}`} />
      </div>

      <div className="mt-8 flex items-center gap-3">
        <button className="btn btn-primary" disabled={!canStart} onClick={() => onStart('standard')}>
          Start a set
        </button>
        <button className="btn" disabled={ov.library === 0} onClick={() => onStart('speed')}>
          Speed run
        </button>
        <span className="ml-2 text-2xs text-muted">
          A set is {ov.set_size} positions or {ov.timebox_min} minutes, whichever ends first. A speed run is {ov.speed_timebox_min} minutes of easier positions.
        </span>
      </div>
      {err && (
        <div className="mt-4">
          <Notice tone="bad">{err}</Notice>
        </div>
      )}

      <Calibration onStart={() => onStart('calibration')} />
      <Library lib={lib} />
    </View>
  )
}

function Calibration({ onStart }: { onStart: () => void }) {
  const { data: c } = useRpc<CalibrationStatus>('calibration.status')
  if (!c) return null
  const daysLeft = c.next_due_at ? Math.max(0, Math.ceil((c.next_due_at - Date.now() / 1000) / 86400)) : 0
  return (
    <section className="card mt-12 grid gap-3 px-6 py-5">
      <div className="flex items-center justify-between gap-6">
        <div className="min-w-0">
          <div className="text-xs text-muted">Calibration</div>
          <div className="mt-0.5 text-sm">
            {c.due ? 'A calibration test is due.' : `Next test in ${daysLeft} day${daysLeft === 1 ? '' : 's'}.`}
            {c.last?.performance != null && (
              <span className="text-muted">
                {' '}
                Last time you performed at <span className="tabular text-text">{num(c.last.performance)}</span>.
              </span>
            )}
          </div>
          <div className="mt-0.5 text-2xs text-faint">
            {c.size} fresh positions from your level − {c.spread} to + {c.spread}, {c.seconds} seconds each, solved cold: no answers until the end, nothing scheduled, every {c.every_days} days.
          </div>
        </div>
        {c.due && (
          <button className="btn shrink-0" onClick={onStart} disabled={!c.library_ready}>
            Start the test
          </button>
        )}
      </div>
      {c.history.length > 1 && (
        <div className="tabular flex flex-wrap gap-x-5 gap-y-1 text-2xs text-muted">
          {c.history.map((h) => (
            <span key={h.finished_at}>
              {dateLong(h.finished_at)} · <span className="text-text">{num(h.performance)}</span>
            </span>
          ))}
        </div>
      )}
    </section>
  )
}

function Library({ lib }: { lib: PuzzleLibrary }) {
  const [err, setErr] = useState<string | null>(null)
  const start = () => brain.call('puzzles.import').catch((e: Error) => setErr(e.message))
  const running = lib.state === 'running'
  return (
    <section className="card mt-12 grid gap-3 px-6 py-5">
      <div className="flex items-center justify-between gap-6">
        <div className="min-w-0">
          <div className="text-xs text-muted">Puzzle library</div>
          <div className="mt-0.5 text-sm">
            {running
              ? `Importing · ${num(lib.kept ?? 0)} puzzles kept so far`
              : lib.count
                ? `${num(lib.count)} Lichess puzzles on this Mac`
                : 'The Lichess puzzle library isn’t on this Mac yet'}
          </div>
          <div className="mt-0.5 text-2xs text-faint">
            {lib.count && !running
              ? 'Only well-rated, often-played puzzles are kept. Sets lean towards the themes behind your own blunders.'
              : `A one-time ${num(lib.download_mb)} MB download. About a quarter of the puzzles are kept: the most popular and most played.`}
          </div>
        </div>
        {!running && (
          <button className="btn shrink-0" onClick={start}>
            {lib.count ? 'Update library' : 'Import library'}
          </button>
        )}
      </div>
      {running && <Progress value={lib.total ? (lib.received ?? 0) / lib.total : 0} />}
      {(lib.error || err) && <Notice tone="bad">{err ?? `The import stopped: ${lib.error}. Puzzles already imported are kept; try again to finish.`}</Notice>}
    </section>
  )
}

// ── A running set ────────────────────────────────────────────────────────────────────────────────

type Phase = 'loading' | 'lead' | 'think' | 'pending' | 'waiting' | 'revealed' | 'recorded'

function Session({ onDone }: { onDone: (s: SolveSummary, reason: EndReason) => void }) {
  const [pos, setPos] = useState<SolvePosition | null>(null)
  const [line, setLine] = useState<Line | null>(null) // from the item's fen: lead-in, then moves
  const [phase, setPhase] = useState<Phase>('loading')
  const [pending, setPending] = useState<string | null>(null)
  const [confidence, setConfidence] = useState<Confidence | null>(null)
  const [typedLine, setTypedLine] = useState('')
  const [san, setSan] = useState('')
  const [reveal, setReveal] = useState<(Reveal & { result: 'solved' | 'wrong'; confidentMiss: boolean; answer: string[] }) | null>(null)
  const [revealPly, setRevealPly] = useState(0)
  const [err, setErr] = useState<string | null>(null)
  const [t0, setT0] = useState(() => Date.now()) // when the set started, from the brain's elapsed time
  const shownAt = useRef(0)
  const answered = useRef<string[]>([])
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])
  const reduce = useReducedMotion()
  const now = useNow(1000)

  const later = (fn: () => void, ms: number) => timers.current.push(setTimeout(fn, reduce ? 0 : ms))
  useEffect(() => () => timers.current.forEach(clearTimeout), [])

  const load = useCallback(() => {
    setPhase('loading')
    setReveal(null)
    setPending(null)
    setConfidence(null)
    setTypedLine('')
    setSan('')
    setErr(null)
    answered.current = []
    brain
      .call<SolveNext>('solve.next')
      .then((n) => {
        if (n.done) return onDone(n.summary, n.reason)
        setPos(n)
        setT0(Date.now() - n.elapsed_min * 60000)
        // Resume mid-item if the brain already has moves for it.
        const resumed = n.played.flatMap((p, i) => (n.replies[i] ? [p, n.replies[i]] : [p]))
        answered.current = [...n.played]
        const base = new Line(n.fen, [])
        if (n.lead_uci && !resumed.length) {
          setLine(base)
          setPhase('lead')
          later(() => {
            setLine(base.push(n.lead_uci!))
            later(() => {
              shownAt.current = performance.now()
              setPhase('think')
            }, 240)
          }, 420)
        } else {
          setLine(new Line(n.fen, [...(n.lead_uci ? [n.lead_uci] : []), ...resumed]))
          shownAt.current = performance.now()
          setPhase('think')
        }
      })
      .catch((e: Error) => setErr(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onDone])

  useEffect(load, [load])

  const firstMove = answered.current.length === 0
  const standard = pos?.mode === 'standard'

  const commit = useCallback(
    (uci: string, conf: Confidence | null) => {
      if (!pos || !line) return
      setPhase('waiting')
      const ms = Math.round(performance.now() - shownAt.current)
      const params: Record<string, unknown> = { item_id: pos.item_id, uci }
      if (answered.current.length === 0) Object.assign(params, { confidence: conf, line: typedLine, ms })
      answered.current = [...answered.current, uci]
      brain
        .call<MoveResult>('solve.move', params)
        .then((r) => {
          const withMove = line.push(uci)
          setLine(withMove)
          setPending(null)
          if (!r.done) {
            later(() => {
              setLine(withMove.push(r.reply_uci))
              setPhase('think')
            }, 320)
            return
          }
          const solved = r.result === 'solved'
          if (pos.mode === 'calibration') {
            // Cold: no answer, no verdict. Move on.
            setPhase('recorded')
            later(load, 500)
            return
          }
          setReveal({ ...r.reveal, result: r.result, confidentMiss: r.confident_miss, answer: answered.current })
          setRevealPly(solved ? r.reveal.solution.length : 0)
          setPhase('revealed')
          if (solved && pos.mode === 'speed') later(load, 650)
        })
        .catch((e: Error) => {
          answered.current = answered.current.slice(0, -1)
          setErr(e.message)
          setPending(null)
          setPhase('think')
        })
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [pos, line, typedLine, load],
  )

  const play = (uci: string) => {
    if (phase !== 'think' || !line) return
    setErr(null)
    if (standard && firstMove && pos?.mode === 'standard') {
      setPending(uci)
      setPhase('pending')
    } else commit(uci, null)
  }

  const takeBack = () => {
    if (phase !== 'pending') return
    setPending(null)
    setPhase('think')
  }

  const endSet = () => brain.call<SolveSummary>('solve.end').then((s) => onDone(s, 'ended'))

  // Keyboard: 1–3 confidence, Enter commits / continues, Esc takes back, ← → step through the answer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.tagName === 'INPUT'
      if (phase === 'pending') {
        if (!typing && ['1', '2', '3'].includes(e.key)) setConfidence(CONFIDENCE[Number(e.key) - 1].value)
        else if (e.key === 'Enter' && confidence && pending) {
          e.preventDefault()
          commit(pending, confidence)
        } else if (e.key === 'Escape') takeBack()
      } else if (phase === 'revealed' && reveal) {
        if (e.key === 'Enter' || (e.key === ' ' && !typing)) {
          e.preventDefault()
          load()
        } else if (e.key === 'ArrowLeft') setRevealPly((p) => Math.max(0, p - 1))
        else if (e.key === 'ArrowRight') setRevealPly((p) => Math.min(reveal.solution.length, p + 1))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  // What the board shows.
  const board = useMemo(() => {
    if (phase === 'revealed' && reveal) {
      const l = new Line(reveal.fen, reveal.solution)
      const v = l.view(revealPly)
      const shapes = []
      if (revealPly === 0) {
        if (reveal.result === 'wrong' && reveal.answer.length) shapes.push(arrow(reveal.answer[reveal.answer.length - 1], 'gold'))
        if (reveal.solution[0]) shapes.push(arrow(reveal.solution[0], 'good'))
      }
      return { ...v, movable: null, shapes }
    }
    if (!line) return null
    const l = pending ? line.push(pending) : line
    const v = l.view()
    return { ...v, movable: phase === 'think' ? v.turn : null, shapes: [] }
  }, [phase, reveal, revealPly, line, pending])

  // Calibration: each position has its own clock; when it runs out, the position counts as unsolved.
  const [itemStart, setItemStart] = useState(() => Date.now())
  useEffect(() => {
    if (phase === 'think' && answered.current.length === 0) setItemStart(Date.now())
  }, [phase, pos?.item_id])
  const itemLeft = pos?.time_limit_s ? Math.max(0, pos.time_limit_s - (now - itemStart) / 1000) : null
  useEffect(() => {
    if (pos?.mode !== 'calibration' || itemLeft == null || itemLeft > 0 || (phase !== 'think' && phase !== 'lead')) return
    setPhase('waiting')
    brain.call('solve.skip', { item_id: pos.item_id }).then(() => {
      setPhase('recorded')
      later(load, 500)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemLeft, phase, pos])

  const orientation = pos?.turn ?? 'white'
  const remaining = pos ? Math.max(0, pos.timebox_min - (now - t0) / 60000) : 0
  const warn = standard && remaining <= 5

  return (
    <div className="grid h-full min-h-[640px] grid-cols-[1fr_360px]">
      <div className="grid place-items-center px-10 pt-12 pb-8" data-tauri-drag-region>
        <div className="aspect-square w-[min(calc(100vh-112px),100%)] rounded-[6px] bg-surface p-2.5 shadow-[0_0_0_0.5px_var(--line),0_12px_32px_-12px_rgb(0_0_0/0.35)]">
          {board && (
            <Board
              fen={board.fen}
              orientation={orientation}
              turnColor={board.turn}
              movable={board.movable}
              dests={board.dests}
              lastMove={board.lastMove}
              check={board.check}
              shapes={board.shapes}
              onMove={(o, d) => line && play(uciFromBoard(line.pos(), o, d))}
            />
          )}
        </div>
      </div>

      <aside className="flex min-h-0 flex-col gap-6 border-l hairline bg-surface px-7 pt-[52px] pb-6">
        <div className="flex items-baseline justify-between">
          <div className="eyebrow">
            {pos?.mode === 'speed' ? 'Speed run' : pos?.mode === 'calibration' ? 'Calibration' : 'Solve'}
            {pos && pos.mode !== 'speed' && (
              <span className="tabular ml-2 text-faint">
                {pos.index + 1} of {pos.total}
              </span>
            )}
          </div>
          {pos && (
            <div className={`tabular text-xs ${warn ? 'text-bad' : 'text-muted'}`} aria-live="polite">
              {pos.mode === 'speed' ? clock(remaining) : pos.mode === 'calibration' && itemLeft != null ? clock(itemLeft / 60) : `${Math.ceil(remaining)} min left`}
            </div>
          )}
        </div>
        {pos && pos.mode !== 'speed' && <Progress value={pos.index / pos.total} />}

        <AnimatePresence mode="wait">
          <motion.div
            key={phase === 'revealed' ? `r${pos?.item_id}` : `p${pos?.item_id}`}
            initial={{ opacity: 0, y: reduce ? 0 : 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="grid gap-6"
          >
            {phase === 'recorded' ? (
              <div>
                <h2 className="display m-0 text-xl">Recorded.</h2>
                <p className="mt-2 mb-0 text-xs text-muted">Answers come at the end of the test.</p>
              </div>
            ) : phase === 'revealed' && reveal ? (
              <RevealPanel r={reveal} ply={revealPly} onStep={setRevealPly} typedLine={typedLine} onNext={load} />
            ) : (
              pos && (
                <Prompt
                  pos={pos}
                  phase={phase}
                  firstMove={firstMove}
                  pendingSan={pending && line ? line.push(pending).sanTokens(line.ucis.length).filter((t) => !t.num)[0]?.text : null}
                  san={san}
                  setSan={setSan}
                  onSan={() => {
                    if (!line) return
                    const u = uciFromSan(line.pos(), san)
                    if (!u) return setErr(`“${san.trim()}” isn’t a legal move here.`)
                    setSan('')
                    play(u)
                  }}
                  typedLine={typedLine}
                  setTypedLine={setTypedLine}
                  confidence={confidence}
                  setConfidence={setConfidence}
                  onCommit={() => pending && confidence && commit(pending, confidence)}
                  onTakeBack={takeBack}
                />
              )
            )}
          </motion.div>
        </AnimatePresence>
        {err && <Notice tone="bad">{err}</Notice>}
        {warn && phase !== 'revealed' && <Notice tone="bad">A few minutes left. The set ends after the position you’re on when time runs out.</Notice>}

        <div className="mt-auto flex justify-between">
          <button className="btn btn-quiet -ml-3" onClick={endSet}>
            End set
          </button>
        </div>
      </aside>
    </div>
  )
}

const clock = (min: number) => {
  const s = Math.ceil(min * 60)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function Prompt(props: {
  pos: SolvePosition
  phase: Phase
  firstMove: boolean
  pendingSan: string | null | undefined
  san: string
  setSan: (s: string) => void
  onSan: () => void
  typedLine: string
  setTypedLine: (s: string) => void
  confidence: Confidence | null
  setConfidence: (c: Confidence) => void
  onCommit: () => void
  onTakeBack: () => void
}) {
  const { pos, phase } = props
  const side = pos.turn === 'white' ? 'White' : 'Black'
  if (phase === 'pending')
    return (
      <>
        <div>
          <div className="text-xs text-muted">Your move</div>
          <div className="mt-1 font-mono text-[32px] leading-none font-light">{props.pendingSan}</div>
        </div>
        <label className="grid gap-1.5">
          <span className="text-xs text-muted">The line you expect (optional)</span>
          <input
            className="field font-mono text-sm"
            value={props.typedLine}
            onChange={(e) => props.setTypedLine(e.target.value)}
            placeholder="e.g. Kh8 Qxf7"
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <div className="grid gap-1.5">
          <span className="text-xs text-muted">How sure are you?</span>
          <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Confidence">
            {CONFIDENCE.map((c) => (
              <button
                key={c.value}
                role="radio"
                aria-checked={props.confidence === c.value}
                onClick={() => props.setConfidence(c.value)}
                className={`flex h-9 items-center justify-center gap-2 rounded-lg border text-xs transition-colors duration-150 ${
                  props.confidence === c.value ? 'border-[var(--text)] bg-surface-2 text-text' : 'hairline text-muted hover:text-text'
                }`}
              >
                {c.label} <kbd>{c.key}</kbd>
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center justify-between">
          <button className="btn btn-quiet -ml-3" onClick={props.onTakeBack}>
            Take back <kbd>esc</kbd>
          </button>
          <button className="btn btn-primary" disabled={!props.confidence} onClick={props.onCommit}>
            Commit <span className="opacity-60">↵</span>
          </button>
        </div>
      </>
    )
  return (
    <>
      <div>
        <h2 className="display m-0 text-xl">{props.firstMove ? `${side} to move.` : 'Keep going.'}</h2>
        <p className="mt-2 mb-0 text-xs text-muted">
          {phase === 'lead'
            ? 'Watch the last move.'
            : props.firstMove
              ? pos.mode === 'speed'
                ? 'First instinct. Your move counts as soon as you play it.'
                : pos.mode === 'calibration'
                ? 'One attempt, against the clock. Your move counts as soon as you play it.'
                : 'Find the best move. Nothing is revealed until you commit.'
              : 'Correct so far. Play the next move.'}
        </p>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          props.onSan()
        }}
        className="grid gap-1.5"
      >
        <label htmlFor="san" className="text-xs text-muted">
          Or type it
        </label>
        <input
          id="san"
          className="field font-mono"
          value={props.san}
          onChange={(e) => props.setSan(e.target.value)}
          placeholder="Nf3, exd5, O-O"
          autoComplete="off"
          spellCheck={false}
          disabled={phase !== 'think'}
        />
      </form>
    </>
  )
}

function RevealPanel({ r, ply, onStep, typedLine, onNext }: { r: Reveal & { result: 'solved' | 'wrong'; confidentMiss: boolean; answer: string[] }; ply: number; onStep: (n: number) => void; typedLine: string; onNext: () => void }) {
  const solved = r.result === 'solved'
  const answerLine = new Line(r.fen, r.solution)
  // Number each move token so a click can jump the board to just after it.
  const tokens = answerLine.sanTokens().reduce<{ text: string; num?: boolean; ply: number }[]>(
    (acc, t) => [...acc, { ...t, ply: (acc.at(-1)?.ply ?? 0) + (t.num ? 0 : 1) }],
    [],
  )
  const yours = r.answer.length && !solved ? new Line(r.fen, [...r.solution.slice(0, r.answer.length - 1), r.answer[r.answer.length - 1]]).sanTokens(r.answer.length - 1).filter((t) => !t.num)[0]?.text : null
  const themes = visibleThemes(r.themes)
  const s = r.source
  return (
    <>
      <div>
        <h2 className={`display m-0 text-xl ${solved ? 'text-good' : ''}`}>{solved ? 'Solved.' : 'Not this one.'}</h2>
        {yours && <p className="mt-2 mb-0 text-xs text-muted">You played <span className="font-mono text-text">{yours}</span>. The gold arrow is yours; the green one is the answer.</p>}
      </div>

      <div className="grid gap-1.5">
        <span className="text-xs text-muted">The answer · step through with ← →</span>
        <div className="flex flex-wrap gap-x-1.5 gap-y-1 font-mono text-sm">
          {tokens.map((t, i) => {
            if (t.num) return <span key={i} className="text-faint">{t.text}</span>
            return (
              <button key={i} onClick={() => onStep(t.ply)} className={`rounded px-1 transition-colors ${ply === t.ply ? 'bg-[var(--active)] text-text' : 'text-text hover:bg-[var(--hover)]'}`}>
                {t.text}
              </button>
            )
          })}
        </div>
        {typedLine.trim() && (
          <span className="text-2xs text-faint">
            Your line: <span className="font-mono">{typedLine.trim()}</span>
          </span>
        )}
      </div>

      {r.confidentMiss && <Notice>You were sure, and it wasn’t this. Those are the misses most worth a second look.</Notice>}

      <dl className="m-0 grid grid-cols-[96px_1fr] gap-x-3 gap-y-2 text-xs">
        <dt className="text-muted">From</dt>
        <dd className="m-0">
          {s.kind === 'own' ? (
            <>
              Your {s.time_class} game{s.opp_name ? ` against ${s.opp_name}` : ''}
              {s.played_at ? `, ${date(s.played_at)}` : ''}, move {s.move_number}
              {s.mirrored && <span className="text-faint"> · colours flipped</span>}
            </>
          ) : (
            <button className="text-left hover:underline" onClick={() => s.url && openExternal(s.url)}>
              Lichess puzzle · <span className="tabular">{num(s.rating)}</span>
            </button>
          )}
        </dd>
        {themes.length > 0 && (
          <>
            <dt className="text-muted">Themes</dt>
            <dd className="m-0">{themes.map(themeWords).join(' · ')}</dd>
          </>
        )}
        {r.next_review_days != null && (
          <>
            <dt className="text-muted">Back</dt>
            <dd className="m-0">{days(r.next_review_days)}</dd>
          </>
        )}
        {s.kind === 'own' && s.platform && (
          <>
            <dt className="text-muted">Game</dt>
            <dd className="m-0 text-muted">{PLATFORM[s.platform]}</dd>
          </>
        )}
      </dl>

      <div className="flex justify-end">
        <button className="btn btn-primary" onClick={onNext} autoFocus>
          Next position <span className="opacity-60">↵</span>
        </button>
      </div>
    </>
  )
}

// ── After a set ──────────────────────────────────────────────────────────────────────────────────

function Summary({ s, reason, onBack }: { s: SolveSummary; reason: EndReason; onBack: () => void }) {
  return (
    <View>
      <Header
        eyebrow={s.mode === 'speed' ? 'Speed run' : s.mode === 'calibration' ? 'Calibration' : 'Solve'}
        title={
          s.mode === 'calibration'
            ? s.performance != null
              ? `You performed at ${num(s.performance)}.`
              : 'Calibration closed.'
            : reason === 'timebox'
              ? 'Time’s up. Set closed.'
              : reason === 'complete'
                ? 'Set done.'
                : 'Set closed early.'
        }
        sub={
          s.mode === 'calibration'
            ? 'A performance rating on the Lichess puzzle scale, from fresh positions solved cold. It moves slowly; compare it across tests, not against your solve rating.'
            : s.attempted
              ? 'Positions you missed come back in about ten minutes, then on their own schedule. The ones you solved come back just before you’d forget them.'
              : 'No positions were attempted.'
        }
      />
      <div className="grid grid-cols-4 gap-6 border-y hairline py-6">
        <Figure label="Solved" value={`${num(s.solved)} of ${num(s.attempted)}`} />
        <Figure label="Sure but wrong" value={num(s.confident_misses)} note="worth a second look" />
        <Figure label="Typical solve" value={s.median_ms ? `${Math.round(s.median_ms / 1000)} s` : '–'} note="median, solved ones" />
        <Figure label="Solving around" value={num(s.solve_rating)} note={`${num(s.minutes)} min`} />
      </div>
      <div className="mt-8">
        <button className="btn" onClick={onBack} autoFocus>
          Back to Solve
        </button>
      </div>
    </View>
  )
}
