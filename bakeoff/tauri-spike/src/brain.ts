type Pending = (value: unknown) => void

declare global {
  interface Window { __GAMBIT__?: { port: number; token: string; bench?: boolean } }
}

/** Minimal JSON-RPC client for the brain's localhost WebSocket. */
export class BrainClient {
  private ws?: WebSocket
  private pending = new Map<number, Pending>()
  private next = 1

  async connect(): Promise<boolean> {
    const cfg = window.__GAMBIT__
    if (!cfg) return false
    for (let attempt = 0; attempt < 40; attempt++) {
      try {
        this.ws = await new Promise<WebSocket>((resolve, reject) => {
          const ws = new WebSocket(`ws://127.0.0.1:${cfg.port}/?t=${cfg.token}`)
          ws.onopen = () => resolve(ws)
          ws.onerror = reject
        })
        this.ws.onmessage = (ev) => {
          const msg = JSON.parse(ev.data)
          this.pending.get(msg.id)?.(msg.result)
          this.pending.delete(msg.id)
        }
        return true
      } catch {
        await new Promise((r) => setTimeout(r, 250))
      }
    }
    return false
  }

  call<T = unknown>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    const id = this.next++
    return new Promise((resolve) => {
      this.pending.set(id, resolve as Pending)
      this.ws?.send(JSON.stringify({ id, method, params }))
    })
  }
}
