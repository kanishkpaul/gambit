import { useCallback, useEffect, useRef, useState } from 'react'
import { brain, type ConnState } from './brain'

/** Call a brain method on mount (and when `deps` change); refetch on the given event topics. */
export function useRpc<T>(method: string, params: Record<string, unknown> = {}, refreshOn: string[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const key = JSON.stringify(params)
  const seq = useRef(0)

  const load = useCallback(() => {
    const mine = ++seq.current
    brain
      .call<T>(method, JSON.parse(key))
      .then((d) => mine === seq.current && (setData(d), setError(null)))
      .catch((e: Error) => mine === seq.current && setError(e.message))
  }, [method, key])

  useEffect(() => {
    load()
    // Throttle event-driven refetches: analysis emits about once a second.
    let timer: ReturnType<typeof setTimeout> | undefined
    const offs = [...refreshOn, 'connection'].map((t) =>
      brain.on(t, (d) => {
        if (t === 'connection' && d !== 'open') return
        clearTimeout(timer)
        timer = setTimeout(load, t === 'connection' ? 0 : 1500)
      }),
    )
    return () => {
      clearTimeout(timer)
      offs.forEach((off) => off())
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, refreshOn.join()])

  return { data, error, reload: load, setData }
}

/** Latest payload of a brain event topic, seeded by an optional initial value. */
export function useEvent<T>(topic: string, initial: T | null = null): T | null {
  const [v, setV] = useState<T | null>(initial)
  useEffect(() => brain.on(topic, (d) => setV(d as T)), [topic])
  useEffect(() => {
    if (initial !== null) setV(initial)
  }, [initial])
  return v
}

export function useConnection(): ConnState {
  const [s, setS] = useState<ConnState>(brain.state)
  useEffect(() => brain.on('connection', (d) => setS(d as ConnState)), [])
  return s
}

/** A clock that re-renders every `ms`. */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(id)
  }, [ms])
  return now
}
