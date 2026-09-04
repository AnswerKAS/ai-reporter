import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'

export type ThemeChoice = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'ai-reporter-theme'

interface ThemeContextValue {
  /** Что выбрал пользователь, включая «как в системе». */
  theme: ThemeChoice
  /** Что реально показано сейчас — с уже развёрнутым system. */
  resolved: 'light' | 'dark'
  setTheme: (next: ThemeChoice) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function readStored(): ThemeChoice {
  const raw = localStorage.getItem(STORAGE_KEY)
  return raw === 'light' || raw === 'dark' || raw === 'system' ? raw : 'system'
}

function systemPrefersDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

/** Класс на <html> ставится и до гидрации — инлайн-скриптом в index.html,
    чтобы при загрузке не мигало светлым. Здесь держим его в актуальном виде. */
function apply(resolved: 'light' | 'dark') {
  const root = document.documentElement
  root.classList.toggle('dark', resolved === 'dark')
  root.style.colorScheme = resolved
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeChoice>(readStored)
  const [systemDark, setSystemDark] = useState(systemPrefersDark)

  // режим system должен реагировать на смену темы ОС без перезагрузки
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])

  const resolved: 'light' | 'dark' = theme === 'system' ? (systemDark ? 'dark' : 'light') : theme

  useEffect(() => {
    apply(resolved)
  }, [resolved])

  const setTheme = useCallback((next: ThemeChoice) => {
    setThemeState(next)
    localStorage.setItem(STORAGE_KEY, next)
  }, [])

  return <ThemeContext.Provider value={{ theme, resolved, setTheme }}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme вне ThemeProvider')
  return ctx
}
