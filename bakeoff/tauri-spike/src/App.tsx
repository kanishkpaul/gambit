import { useEffect, useRef, useState } from 'react'
import { Chessground } from '@lichess-org/chessground'
import type { Api } from '@lichess-org/chessground/api'
import type { Key } from '@lichess-org/chessground/types'
import type { DrawBrushes } from '@lichess-org/chessground/draw'
import { Chess } from 'chessops/chess'
import { chessgroundDests } from 'chessops/compat'
import { makeFen } from 'chessops/fen'
import { parseSan, makeSan } from 'chessops/san'
import { makeSquare, parseSquare } from 'chessops/util'
import type { NormalMove } from 'chessops/types'
import { BrainClient } from './brain'
import { runFrameBench } from './bench'

const NAV = ['Mirror', 'Solve', 'Calculation', 'Game Lab', 'Endgames', 'Slope']

export default function App() {
  const boardEl = useRef<HTMLDivElement>(null)
  const cg = useRef<Api | null>(null)
  const pos = useRef(Chess.default())
  const [moves, setMoves] = useState<string[]>([])
  const [input, setInput] = useState('')
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')

  const sync = () => {
    const p = pos.current
    cg.current?.set({
      fen: makeFen(p.toSetup()),
      turnColor: p.turn,
      movable: { color: p.turn, dests: chessgroundDests(p) },
      check: p.isCheck(),
    })
  }

  const play = (move: NormalMove, animateOnBoard: boolean) => {
    const p = pos.current
    const san = makeSan(p, move)
    p.play(move)
    setMoves((m) => [...m, san])
    if (animateOnBoard) cg.current?.move(makeSquare(move.from) as Key, makeSquare(move.to) as Key)
    sync()
    const from = makeSquare(move.from) as Key, to = makeSquare(move.to) as Key
    cg.current?.setAutoShapes([{ orig: from, dest: to, brush: 'gold' }])
  }

  useEffect(() => {
    if (!boardEl.current) return
    cg.current = Chessground(boardEl.current, {
      animation: { enabled: true, duration: 220 },
      highlight: { lastMove: true, check: true },
      coordinates: true,
      drawable: {
        brushes: {
          gold: { key: 'gold', color: '#C9A86A', opacity: 0.85, lineWidth: 9 },
          muted: { key: 'muted', color: '#A7A196', opacity: 0.5, lineWidth: 7 },
        } as Partial<DrawBrushes> as DrawBrushes,
      },
      movable: {
        free: false,
        events: {
          after: (orig, dest) => {
            const move = { from: parseSquare(orig)!, to: parseSquare(dest)! } as NormalMove
            const piece = pos.current.board.get(move.from)
            if (piece?.role === 'pawn' && (dest[1] === '8' || dest[1] === '1')) move.promotion = 'queen'
            play(move, false)
          },
        },
      },
    })
    sync()
    if (location.hash === '#bench' || window.__GAMBIT__?.bench) {
      const brain = new BrainClient()
      setStatus('Benchmark running')
      runFrameBench(brain, cg.current, pos, play, () => { pos.current = Chess.default(); setMoves([]); sync() })
        .then((r) => setStatus(`Benchmark saved · loaded p95 ${r.loaded.p95_ms} ms`))
    }
    return () => cg.current?.destroy()
  }, [])

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const move = parseSan(pos.current, input.trim())
    if (!move || !('from' in move)) {
      setError(`"${input.trim()}" isn't a legal move here`)
      return
    }
    setError('')
    setInput('')
    play(move, true)
  }

  return (
    <div className="shell">
      <aside className="sidebar" data-tauri-drag-region>
        <div className="wordmark">gambit</div>
        <nav>
          {NAV.map((n) => (
            <button key={n} className={n === 'Game Lab' ? 'nav active' : 'nav'}>{n}</button>
          ))}
        </nav>
        <div className="sidebar-foot">Fair-play lock off</div>
      </aside>

      <main className="stage" data-tauri-drag-region>
        <div className="board-frame">
          <div ref={boardEl} className="board" />
        </div>
      </main>

      <section className="rail">
        <header>
          <div className="eyebrow">Game Lab</div>
          <h1>Your analysis first</h1>
          <p className="muted">The engine stays locked until you commit.</p>
        </header>
        <ol className="moves">
          {Array.from({ length: Math.ceil(moves.length / 2) }, (_, i) => (
            <li key={i}>
              <span className="num">{i + 1}</span>
              <span>{moves[2 * i]}</span>
              <span>{moves[2 * i + 1] ?? ''}</span>
            </li>
          ))}
        </ol>
        <form onSubmit={submit} className="san">
          <label htmlFor="san">Type a move</label>
          <input id="san" value={input} onChange={(e) => setInput(e.target.value)} placeholder="e4, Nf3, O-O" autoComplete="off" spellCheck={false} />
          {error && <p className="error">{error}</p>}
        </form>
        {status && <p className="status">{status}</p>}
      </section>
    </div>
  )
}
