import * as Plot from '@observablehq/plot'
import { useEffect, useRef, useState } from 'react'

/** Renders an Observable Plot at the container's width, re-rendering on resize and theme change. */
export function PlotFigure({
  make,
  height,
  label,
}: {
  make: (width: number) => Plot.PlotOptions
  height: number
  label: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const [scheme, setScheme] = useState(() => matchMedia('(prefers-color-scheme: light)').matches)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)))
    ro.observe(el)
    const mq = matchMedia('(prefers-color-scheme: light)')
    const onScheme = () => setScheme(mq.matches)
    mq.addEventListener('change', onScheme)
    return () => {
      ro.disconnect()
      mq.removeEventListener('change', onScheme)
    }
  }, [])

  useEffect(() => {
    const el = ref.current
    if (!el || width < 50) return
    const fig = Plot.plot({ width, height, ...make(width) })
    fig.setAttribute('role', 'img')
    fig.setAttribute('aria-label', label)
    el.replaceChildren(fig)
    return () => fig.remove()
  }, [make, width, height, scheme, label])

  return <div ref={ref} className="plot w-full" style={{ height }} />
}

/** Resolved CSS token, so Plot marks follow the theme. */
export const tok = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim()
