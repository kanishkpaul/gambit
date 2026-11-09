import { Chessground } from '@lichess-org/chessground'
import type { Api } from '@lichess-org/chessground/api'
import type { DrawShape } from '@lichess-org/chessground/draw'
import type { Dests, Key } from '@lichess-org/chessground/types'
import { useEffect, useRef } from 'react'
import '@lichess-org/chessground/assets/chessground.base.css'
import './board.css'

export type Color = 'white' | 'black'

export interface BoardProps {
  fen: string
  orientation: Color
  turnColor: Color
  /** Side that may move, or null for a frozen board. */
  movable: Color | null
  dests: Dests
  lastMove?: [string, string]
  check?: boolean
  shapes?: DrawShape[]
  onMove?: (orig: string, dest: string) => void
}

/**
 * A thin, controlled wrapper over chessground: every prop change becomes one `set()`, and
 * chessground animates the difference between positions itself.
 */
export function Board({ fen, orientation, turnColor, movable, dests, lastMove, check, shapes = [], onMove }: BoardProps) {
  const el = useRef<HTMLDivElement>(null)
  const cg = useRef<Api | null>(null)
  const moveRef = useRef(onMove)
  useEffect(() => {
    moveRef.current = onMove
  }, [onMove])

  useEffect(() => {
    if (!el.current) return
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
    // SVG attributes can't read CSS variables, so resolve the tokens once.
    const tok = (n: string) => getComputedStyle(document.documentElement).getPropertyValue(`--${n}`).trim()
    cg.current = Chessground(el.current, {
      animation: { enabled: !reduce, duration: 220 },
      highlight: { lastMove: true, check: true },
      coordinates: true,
      coordinatesOnSquares: false,
      autoCastle: true,
      premovable: { enabled: false },
      draggable: { showGhost: true },
      drawable: {
        enabled: true, // right-click arrows and circles: your own thinking aid
        visible: true,
        brushes: {
          gold: { key: 'gold', color: tok('gold'), opacity: 0.9, lineWidth: 8 },
          good: { key: 'good', color: tok('good'), opacity: 0.9, lineWidth: 8 },
          muted: { key: 'muted', color: tok('muted'), opacity: 0.55, lineWidth: 7 },
          green: { key: 'green', color: '#15781B', opacity: 1, lineWidth: 10 },
          red: { key: 'red', color: '#882020', opacity: 1, lineWidth: 10 },
          blue: { key: 'blue', color: '#003088', opacity: 1, lineWidth: 10 },
          yellow: { key: 'yellow', color: '#e68f00', opacity: 1, lineWidth: 10 },
        },
      },
      movable: { free: false, showDests: true, events: { after: (o, d) => moveRef.current?.(o, d) } },
    })
    return () => cg.current?.destroy()
  }, [])

  useEffect(() => {
    cg.current?.set({
      fen,
      orientation,
      turnColor,
      check: check ? turnColor : false,
      lastMove: lastMove as Key[] | undefined,
      movable: { color: movable ?? undefined, dests: movable ? dests : new Map() },
      viewOnly: false,
    })
  }, [fen, orientation, turnColor, movable, dests, lastMove, check])

  useEffect(() => {
    cg.current?.setAutoShapes(shapes)
  }, [shapes])

  return <div ref={el} className="gambit-board h-full w-full" />
}
