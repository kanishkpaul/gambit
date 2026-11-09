/** JSON-RPC client for the brain's localhost WebSocket. Reconnects on its own; queues calls while down. */

declare global {
  interface Window {
    __GAMBIT__?: { port: number; token: string }
  }
}

export class RpcError extends Error {
  code: number
  constructor(message: string, code: number) {
    super(message)
    this.code = code
  }
}

type Pending = { resolve: (v: unknown) => void; reject: (e: Error) => void }
type Listener = (data: unknown) => void
export type ConnState = 'connecting' | 'open' | 'down'

// In a plain browser (`npm run dev` + `npm run brain`) the brain listens on a fixed dev port.
const target = () => window.__GAMBIT__ ?? { port: 8765, token: 'dev' }

class Brain {
  private ws?: WebSocket
  private pending = new Map<number, Pending>()
  private queue: string[] = []
  private listeners = new Map<string, Set<Listener>>()
  private next = 1
  private retry = 0
  state: ConnState = 'connecting'

  constructor() {
    this.connect()
  }

  private setState(s: ConnState) {
    this.state = s
    this.fire('connection', s)
  }

  private connect() {
    const { port, token } = target()
    const ws = new WebSocket(`ws://127.0.0.1:${port}/?t=${token}`)
    this.ws = ws
    ws.onopen = () => {
      this.retry = 0
      this.setState('open')
      for (const m of this.queue.splice(0)) ws.send(m)
    }
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data)
      if (msg.method === 'event') return this.fire(msg.params.topic, msg.params.data)
      const p = this.pending.get(msg.id)
      if (!p) return
      this.pending.delete(msg.id)
      if (msg.error) p.reject(new RpcError(msg.error.message, msg.error.code))
      else p.resolve(msg.result)
    }
    ws.onclose = () => {
      for (const p of this.pending.values()) p.reject(new RpcError('The brain disconnected.', -1))
      this.pending.clear()
      // The brain starts in about a second; after that, back off gently.
      this.setState(this.retry < 12 ? 'connecting' : 'down')
      const delay = Math.min(250 * 2 ** Math.max(0, this.retry - 4), 4000)
      this.retry++
      setTimeout(() => this.connect(), delay)
    }
  }

  call<T = unknown>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    const id = this.next++
    const msg = JSON.stringify({ id, method, params })
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject })
      if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(msg)
      else this.queue.push(msg)
    })
  }

  on(topic: string, fn: Listener): () => void {
    let set = this.listeners.get(topic)
    if (!set) this.listeners.set(topic, (set = new Set()))
    set.add(fn)
    return () => set.delete(fn)
  }

  private fire(topic: string, data: unknown) {
    this.listeners.get(topic)?.forEach((fn) => fn(data))
  }
}

export const brain = new Brain()
