import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

try {
  const theme = localStorage.getItem('theme')
  if (theme === 'light' || theme === 'dark') document.documentElement.setAttribute('data-theme', theme)
} catch {
  /* storage unavailable: follow the system theme */
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// Offline shell + installable app. Service workers need a secure context (localhost or HTTPS).
if ('serviceWorker' in navigator && window.isSecureContext && import.meta.env.PROD) {
  navigator.serviceWorker.register('/sw.js').catch(() => {})
}
