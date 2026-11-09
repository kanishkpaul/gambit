import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// No StrictMode: its double-mounted effects would run the frame benchmark twice.
createRoot(document.getElementById('root')!).render(<App />)
