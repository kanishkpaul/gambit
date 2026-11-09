import type { DrawShape } from '@lichess-org/chessground/draw'
import type { Dests, Key } from '@lichess-org/chessground/types'
import { Chess, normalizeMove } from 'chessops/chess'
import { chessgroundDests } from 'chessops/compat'
import { makeFen, parseFen } from 'chessops/fen'
import { makeSan, parseSan } from 'chessops/san'
import type { NormalMove } from 'chessops/types'
import { makeUci, parseSquare, parseUci } from 'chessops/util'

/** Client-side chess for display and legality only. The brain grades. */
export class Line {
  readonly start: string
  readonly ucis: string[]

  constructor(fen: string, ucis: string[] = []) {
    this.start = fen
    this.ucis = ucis
  }

  pos(upTo = this.ucis.length): Chess {
    const p = Chess.fromSetup(parseFen(this.start).unwrap()).unwrap()
    for (const u of this.ucis.slice(0, upTo)) {
      const m = parseUci(u)
      if (!m) break
      const n = normalizeMove(p, m)
      if (!p.isLegal(n)) break
      p.play(n)
    }
    return p
  }

  push(uci: string): Line {
    return new Line(this.start, [...this.ucis, uci])
  }

  view(upTo = this.ucis.length) {
    const p = this.pos(upTo)
    const last = upTo > 0 ? this.ucis[upTo - 1] : undefined
    return {
      fen: makeFen(p.toSetup()),
      turn: p.turn,
      dests: chessgroundDests(p) as Dests,
      check: p.isCheck(),
      lastMove: last ? ([last.slice(0, 2), last.slice(2, 4)] as [string, string]) : undefined,
    }
  }

  /** SAN with move numbers, e.g. ["1.", "Nf3+", "Kh8", "2.", "Qxf7"]. */
  sanTokens(from = 0, upTo = this.ucis.length): { text: string; num?: boolean }[] {
    const p = this.pos(from)
    const out: { text: string; num?: boolean }[] = []
    for (let i = from; i < upTo; i++) {
      const raw = parseUci(this.ucis[i])
      if (!raw) break
      const m = normalizeMove(p, raw)
      if (!p.isLegal(m)) break
      if (p.turn === 'white') out.push({ text: `${p.fullmoves}.`, num: true })
      else if (i === from) out.push({ text: `${p.fullmoves}…`, num: true })
      out.push({ text: makeSan(p, m) })
      p.play(m)
    }
    return out
  }
}

/** Board move → UCI, promoting to a queen (typed SAN can choose another piece). */
export function uciFromBoard(pos: Chess, orig: string, dest: string): string {
  const piece = pos.board.get(parseSquare(orig)!)
  // Castling dropped on the rook (e1h1) becomes the standard king move (e1g1).
  if (piece?.role === 'king' && orig[0] === 'e' && Math.abs(dest.charCodeAt(0) - orig.charCodeAt(0)) > 1) {
    dest = `${dest[0] > 'e' ? 'g' : 'c'}${dest[1]}`
  }
  const promo = piece?.role === 'pawn' && (dest[1] === '8' || dest[1] === '1') ? 'q' : ''
  return `${orig}${dest}${promo}`
}

export function uciFromSan(pos: Chess, san: string): string | null {
  const m = parseSan(pos, san.trim())
  if (!m || !('from' in m)) return null
  const u = makeUci(m as NormalMove)
  const base = uciFromBoard(pos, u.slice(0, 2), u.slice(2, 4)) // standard castling notation
  return u.length > 4 ? base.slice(0, 4) + u[4] : base // keep a typed under-promotion
}

export function arrow(uci: string, brush: string): DrawShape {
  return { orig: uci.slice(0, 2) as Key, dest: uci.slice(2, 4) as Key, brush }
}
