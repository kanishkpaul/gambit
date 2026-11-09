import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

// chessground hard-codes a cubic in-out easing. DESIGN.md asks for spring-like piece motion,
// so swap in a critically damped spring curve (no overshoot). Fails loudly if chessground changes.
const springEasing = (): Plugin => ({
  name: 'chessground-spring-easing',
  transform(code, id) {
    if (!id.includes('@lichess-org/chessground/dist/anim.js')) return
    const target = 'const easing = (t) => (t < 0.5 ? 4 * t * t * t : (t - 1) * (2 * t - 2) * (2 * t - 2) + 1);'
    if (!code.includes(target)) throw new Error('chessground easing changed; update the patch')
    return code.replace(target, 'const easing = (t) => (t >= 1 ? 1 : 1 - Math.exp(-7 * t) * (1 + 7 * t));')
  },
})

export default defineConfig({
  plugins: [react(), tailwindcss(), springEasing()],
  optimizeDeps: { exclude: ['@lichess-org/chessground'] },
  server: { port: 5173, strictPort: true },
  clearScreen: false,
})
