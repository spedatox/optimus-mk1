import { useEffect, useReducer, useState } from 'react'
import { ChatContext, chatReducer, initialState } from './store/chat'
import { SettingsContext, useSettingsProvider } from './store/settings'
import { ProfileContext } from './components/Sidebar'
import PROFILE from './profile/optimus'
import Layout from './components/Layout'
import HudFrame from './components/HudFrame'
import type { AppConfig } from './lib/types'
import { fetchSessions } from './lib/api'
import 'katex/dist/katex.min.css'
import './theme/heartbreaker.css'

// Optional server override, persisted in the renderer between launches.
const SERVER_KEY = 'optimus.server'

function injectProfileTheme(accent: string, accentHover: string) {
  const root = document.documentElement
  root.style.setProperty('--accent', accent)
  root.style.setProperty('--accent-hover', accentHover)
  root.style.setProperty('--accent-muted', accent + '26')
}

function AppInner() {
  const [state, dispatch] = useReducer(chatReducer, initialState)
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => { injectProfileTheme(PROFILE.accent, PROFILE.accentHover) }, [])

  // Load base config (server + service key). Login is disabled — the service
  // X-API-Key authenticates every request, so we go straight into the app.
  useEffect(() => {
    const load = async () => {
      let base: AppConfig
      if (window.api?.getConfig) {
        const raw = await window.api.getConfig()
        base = { apiBase: raw.apiBase, apiKey: raw.apiKey }
      } else {
        base = {
          apiBase: (import.meta.env.VITE_API_BASE as string) || 'http://localhost:8000',
          apiKey: (import.meta.env.VITE_API_KEY as string) || 'dev-key',
        }
      }
      const savedServer = localStorage.getItem(SERVER_KEY)
      if (savedServer) base = { ...base, apiBase: savedServer }
      setConfig(base)
      setChecking(false)
    }
    load()
  }, [])

  // Once config is loaded, pull the session list (sent with the service key).
  useEffect(() => {
    if (!config) return
    dispatch({ type: 'SET_CONFIG', payload: config })
    fetchSessions(config)
      .then((sessions) => dispatch({ type: 'SET_SESSIONS', payload: sessions }))
      .catch(() => { /* backend not available */ })
  }, [config])

  if (checking || !config) {
    return (
      <div style={{
        height: '100%', display: 'flex', flexDirection: 'column', gap: '0.5rem',
        alignItems: 'center', justifyContent: 'center',
        background: 'var(--bg-primary)',
        fontFamily: "'Share Tech Mono', monospace", letterSpacing: '0.12em',
        fontSize: '0.72rem',
      }}>
        <span style={{ color: 'var(--hb-cyan)' }}>Loading configuration…</span>
      </div>
    )
  }

  return (
    <ChatContext.Provider value={{ state, dispatch }}>
      <ProfileContext.Provider value={PROFILE}>
        <HudFrame />
        <Layout profile={PROFILE} config={config} />
      </ProfileContext.Provider>
    </ChatContext.Provider>
  )
}

export default function App() {
  const settingsCtx = useSettingsProvider()
  return (
    <SettingsContext.Provider value={settingsCtx}>
      <AppInner />
    </SettingsContext.Provider>
  )
}
