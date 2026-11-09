import { useEffect, useState } from 'react'
import { Board } from '../components/Board'
import { LevelLabel, ScaleNote } from '../components/HumanLevel'
import { Header, Notice, Section, Segmented, View } from '../components/ui'
import type { ViewId } from '../components/Sidebar'
import { brain } from '../lib/brain'
import { Line, uciFromBoard } from '../lib/chess'
import { num, pct } from '../lib/format'
import { useRpc } from '../lib/hooks'
import type { HumanLevel, PersonalScale, SparringGame, SparringOver, SparringOverview, SparringReply } from '../lib/types'

export function Sparring({ onGo }: { onGo: (v: ViewId) => void }) {
  const { data, reload } = useRpc<SparringOverview>('sparring.overview')
  const [game, setGame] = useState<SparringGame | null>(null)
  const current = game ?? data?.game ?? null
  if (current) return <Play g={current} onEnd={() => (setGame(null), reload())} onGo={onGo} />
  return <Setup ov={data} onStarted={setGame} />
}

// ── Choosing an opponent ────────────────────────────────────────────────────────────────────────

function Setup({ ov, onStarted }: { ov: SparringOverview | null; onStarted: (g: SparringGame) => void }) {
  const { data: scale } = useRpc<PersonalScale | null>('human.scale')
  const [level, setLevel] = useState<number | null>(null)
  const [label, setLabel] = useState<HumanLevel | null>(null)
  const [color, setColor] = useState<'white' | 'black' | 'random'>('random')
  const [tc, setTc] = useState('15+10')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const lv = level ?? ov?.suggested_level ?? 1100

  useEffect(() => {
    brain.call<HumanLevel>('human.describe', { level: lv }).then(setLabel).catch(() => {})
  }, [lv])

  if (!ov)
    return (
      <View>
        <Header eyebrow="Sparring" title={<span className="text-faint">Setting up the board…</span>} />
      </View>
    )
  const start = () => {
    const [base_min, inc_s] = tc.split('+').map(Number)
    setBusy(true)
    setErr(null)
    brain
      .call<SparringGame>('sparring.start', { color, base_min, inc_s, level: lv })
      .then(onStarted)
      .catch((e: Error) => setErr(e.message))
      .finally(() => setBusy(false))
  }
  const rec = ov.record.find((r) => r.level === lv)
  return (
    <View>
      <Header
        eyebrow="Sparring"
        title="A human-like opponent, at a level you can read."
        sub="Maia-3 learned from millions of human games at every rating, so it makes the mistakes people at that rating make, not engine moves. Long time controls only: this is for thinking, not speed."
      />

      <section className="card grid gap-6 px-7 py-6">
        <div className="grid grid-cols-[1fr_auto] items-start gap-8">
          {label && <LevelLabel h={label} />}
          <div className="flex items-center gap-2">
            <button className="btn btn-quiet" onClick={() => setLevel(Math.max(600, lv - 100))} aria-label="Weaker">
              −
            </button>
            <span className="tabular w-16 text-center font-mono text-sm">{num(lv)}</span>
            <button className="btn btn-quiet" onClick={() => setLevel(Math.min(2600, lv + 100))} aria-label="Stronger">
              +
            </button>
          </div>
        </div>
        <div className="text-2xs text-muted">
          Suggested: Maia {num(ov.suggested_level)}, a little above the {num(ov.your_elo)} gambit uses for you.
          {rec ? ` Your record against this level: ${rec.w}–${rec.d}–${rec.l} (${pct(rec.score)}).` : ''}
        </div>
        {scale && <ScaleNote ready={scale.ready} games={scale.games} needed={scale.needed} beyond={scale.beyond} />}

        <div className="flex flex-wrap items-center gap-6 border-t hairline pt-5">
          <label className="flex items-center gap-3 text-xs text-muted">
            You play
            <Segmented label="Colour" value={color} options={[{ value: 'white', label: 'White' }, { value: 'black', label: 'Black' }, { value: 'random', label: 'Either' }]} onChange={setColor} />
          </label>
          <label className="flex items-center gap-3 text-xs text-muted">
            Clock
            <Segmented label="Time control" value={tc} options={ov.time_controls.map(([m, s]) => ({ value: `${m}+${s}`, label: `${m}+${s}` }))} onChange={setTc} />
          </label>
          <button className="btn btn-primary ml-auto" onClick={start} disabled={busy}>
            {busy ? 'Waking Maia…' : 'Start the game'}
          </button>
        </div>
        {err && <Notice tone="bad">{err}</Notice>}
      </section>

      <Section title="Your results against each level" note="The label is checked against these">
        {ov.record.length ? (
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="text-left text-2xs text-faint">
                <th className="pb-2 font-normal">Maia level</th>
                <th className="pb-2 text-right font-normal">Games</th>
                <th className="pb-2 text-right font-normal">Won · drawn · lost</th>
                <th className="pb-2 text-right font-normal">Score</th>
              </tr>
            </thead>
            <tbody className="tabular">
              {ov.record.map((r) => (
                <tr key={r.level} className="h-9 border-t hairline">
                  <td>{num(r.level)}</td>
                  <td className="text-right">{r.n}</td>
                  <td className="text-right">
                    {r.w} · {r.d} · {r.l}
                  </td>
                  <td className="text-right">{pct(r.score)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="m-0 text-xs text-muted">No games yet. Scoring about half your games against a level means it really is your level, whatever its label says.</p>
        )}
      </Section>
    </View>
  )
}

// ── A game ──────────────────────────────────────────────────────────────────────────────────────

const fmt = (s: number) => {
  const t = Math.max(0, Math.ceil(s))
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`
}

function Play({ g, onEnd, onGo }: { g: SparringGame; onEnd: () => void; onGo: (v: ViewId) => void }) {
  const [line, setLine] = useState(() => new Line('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1', [...g.moves, ...(g.reply ? [g.reply.uci] : [])]))
  const [clocks, setClocks] = useState(g.reply?.clocks ?? g.clocks)
  const [thinking, setThinking] = useState(false)
  const [over, setOver] = useState<SparringOver | null>(g.reply?.over ?? null)
  const [err, setErr] = useState<string | null>(null)
  const [turnStart, setTurnStart] = useState(() => Date.now())
  const [now, setNow] = useState(() => Date.now())
  const v = line.view()
  const yourTurn = v.turn === g.you && !thinking && !over
  const elapsed = yourTurn ? Math.max(0, now - turnStart) / 1000 : 0
  const yourClock = clocks[g.you] - elapsed

  // Your clock runs locally while it's your move; the brain charges the bot's thinking time itself.
  useEffect(() => {
    if (!yourTurn) return
    const t0 = Date.now()
    setTurnStart(t0)
    setNow(t0)
    const id = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(id)
  }, [yourTurn, line])

  useEffect(() => {
    if (yourTurn && yourClock <= 0) brain.call<{ over: SparringOver }>('sparring.flag').then((r) => setOver(r.over))
  }, [yourTurn, yourClock])

  const play = (uci: string) => {
    if (!yourTurn) return
    const left = Math.max(0, yourClock)
    const withMove = line.push(uci)
    setLine(withMove)
    setThinking(true)
    setClocks((c) => ({ ...c, [g.you]: left + g.inc_s }))
    brain
      .call<{ reply?: SparringReply; over?: SparringOver }>('sparring.move', { uci, clock_ms: Math.round(left * 1000) })
      .then((r) => {
        if (r.over) {
          setOver(r.over)
          setThinking(false)
          return
        }
        const reply = r.reply!
        // Show a human pace, but never make you wait more than a few seconds; the bot's clock is charged in full.
        setTimeout(() => {
          setLine(withMove.push(reply.uci))
          setClocks(reply.clocks)
          setThinking(false)
          if (reply.over) setOver(reply.over)
        }, Math.min(reply.think_ms, 3500))
      })
      .catch((e: Error) => {
        setLine(line)
        setErr(e.message)
        setThinking(false)
      })
  }

  const resign = () => brain.call<{ over: SparringOver }>('sparring.resign').then((r) => setOver(r.over))
  const claim = () =>
    brain
      .call<{ over: SparringOver }>('sparring.claim_draw')
      .then((r) => setOver(r.over))
      .catch((e: Error) => setErr(e.message))
  const postMortem = () => over?.game_id && brain.call('lab.open', { game_id: over.game_id }).then(() => onGo('lab')).catch((e: Error) => setErr(e.message))

  const bot = g.you === 'white' ? 'black' : 'white'
  const clock = (side: 'white' | 'black', label: string) => {
    const running = !over && v.turn === side
    const t = side === g.you ? yourClock : clocks[side]
    return (
      <div className={`flex items-baseline justify-between rounded-lg border px-4 py-3 ${running ? 'border-[var(--text)]' : 'hairline'}`}>
        <span className="text-xs text-muted">{label}</span>
        <span className={`tabular font-mono text-xl ${t < 30 && running ? 'text-bad' : ''}`}>{fmt(t)}</span>
      </div>
    )
  }

  return (
    <div className="grid h-full min-h-[640px] grid-cols-[1fr_360px]">
      <div className="grid place-items-center px-10 pt-12 pb-8" data-tauri-drag-region>
        <div className="aspect-square w-[min(calc(100vh-112px),100%)] rounded-[6px] bg-surface p-2.5 shadow-[0_0_0_0.5px_var(--line),0_12px_32px_-12px_rgb(0_0_0/0.35)]">
          <Board fen={v.fen} orientation={g.you} turnColor={v.turn} movable={yourTurn ? g.you : null} dests={v.dests} lastMove={v.lastMove} check={v.check} onMove={(o, d) => play(uciFromBoard(line.pos(), o, d))} />
        </div>
      </div>
      <aside className="flex min-h-0 flex-col gap-5 border-l hairline bg-surface px-7 pt-[52px] pb-6">
        <div className="eyebrow">Sparring · Maia {num(g.level)}</div>
        <LevelLabel h={g.label} size="sm" showScale={false} />
        {clock(bot, `Maia${thinking ? ' · thinking' : ''}`)}
        <div className="max-h-[220px] min-h-[80px] overflow-y-auto font-mono text-xs leading-6 text-muted">
          {line.sanTokens().map((t, i) => (
            <span key={i} className={t.num ? 'mr-1 text-faint' : 'mr-2 text-text'}>
              {t.text}
            </span>
          ))}
        </div>
        {clock(g.you, 'You')}
        {over ? (
          <div className="grid gap-3">
            <h2 className={`display m-0 text-xl ${over.result === 'win' ? 'text-good' : ''}`}>
              {over.result === 'win' ? 'You won.' : over.result === 'draw' ? 'Drawn.' : 'Maia won.'} <span className="text-sm text-muted">({over.reason})</span>
            </h2>
            {over.record && (
              <p className="m-0 text-xs text-muted">
                Against Maia {num(over.level)} you’re now {over.record.w}–{over.record.d}–{over.record.l}, {pct(over.record.score)}.
              </p>
            )}
            <div className="flex justify-between">
              <button className="btn" onClick={onEnd}>
                Back
              </button>
              <button className="btn btn-primary" onClick={postMortem} disabled={!over.game_id}>
                Open post-mortem
              </button>
            </div>
          </div>
        ) : (
          <div className="flex gap-2">
            <button className="btn" onClick={claim}>
              Claim a draw
            </button>
            <button className="btn btn-quiet ml-auto" onClick={resign}>
              Resign
            </button>
          </div>
        )}
        {err && <Notice tone="bad">{err}</Notice>}
        <p className="mt-auto mb-0 text-2xs text-faint">No engine, no hints, no evaluation during the game. Analysis opens after it, in Game Lab.</p>
      </aside>
    </div>
  )
}
