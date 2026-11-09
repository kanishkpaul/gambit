import type { Api } from '@lichess-org/chessground/api'
import type { Chess } from 'chessops/chess'
import { parseSan } from 'chessops/san'
import type { NormalMove } from 'chessops/types'
import type { BrainClient } from './brain'

// Morphy's Opera Game: 33 plies with captures, checks and a mate.
const GAME = 'e4 e5 Nf3 d6 d4 Bg4 dxe5 Bxf3 Qxf3 dxe5 Bc4 Nf6 Qb3 Qe7 Nc3 c6 Bg5 b5 Nxb5 cxb5 Bxb5+ Nbd7 O-O-O Rd8 Rxd7 Rxd7 Rd1 Qe6 Bxd7+ Nxd7 Qb8+ Nxb8 Rd8#'.split(' ')

type Stats = { frames: number; p50_ms: number; p95_ms: number; p99_ms: number; max_ms: number; over_25ms: number; fps: number }

function stats(deltas: number[]): Stats {
  const s = [...deltas].sort((a, b) => a - b)
  const q = (p: number) => +s[Math.floor(p * (s.length - 1))].toFixed(2)
  const total = deltas.reduce((a, b) => a + b, 0)
  return { frames: deltas.length, p50_ms: q(0.5), p95_ms: q(0.95), p99_ms: q(0.99), max_ms: +s[s.length - 1].toFixed(2),
    over_25ms: deltas.filter((d) => d > 25).length, fps: +(1000 * deltas.length / total).toFixed(1) }
}

async function phase(posRef: { current: Chess }, play: (m: NormalMove, anim: boolean) => void, reset: () => void): Promise<Stats> {
  reset()
  const deltas: number[] = []
  let last = performance.now(), running = true
  const tick = (now: number) => { deltas.push(now - last); last = now; if (running) requestAnimationFrame(tick) }
  requestAnimationFrame((now) => { last = now; requestAnimationFrame(tick) })
  for (const san of GAME) {
    const move = parseSan(posRef.current, san) as NormalMove
    play(move, true)
    await new Promise((r) => setTimeout(r, 320))
  }
  running = false
  return stats(deltas.slice(2))
}

export async function runFrameBench(brain: BrainClient, _cg: Api | null, posRef: { current: Chess },
  play: (m: NormalMove, anim: boolean) => void, reset: () => void) {
  await brain.connect()
  await new Promise((r) => setTimeout(r, 1500))
  const idle = await phase(posRef, play, reset)
  await brain.call('load', { engines: 4 })
  await new Promise((r) => setTimeout(r, 2000))
  const loaded = await phase(posRef, play, reset)
  const result = { idle, loaded, devicePixelRatio: window.devicePixelRatio, userAgent: navigator.userAgent }
  await brain.call('report', { name: 'tauri_frames.json', data: result })
  return result
}
