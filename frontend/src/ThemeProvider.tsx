import { createContext, useContext, useEffect, useLayoutEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Moon, Sun } from 'lucide-react'

type Theme = 'dark' | 'light'
const storageKey = 'lifelab-theme'
const ThemeContext = createContext<{theme: Theme; toggle: () => void} | null>(null)

export function ThemeProvider({children}: {children: ReactNode}) {
  const [theme, setTheme] = useState<Theme>(() => document.documentElement.dataset.theme === 'light' ? 'light' : 'dark')
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#090f18' : '#f1f5f8')
    try {localStorage.setItem(storageKey, theme)} catch { /* The current tab still works when storage is unavailable. */ }
  }, [theme])
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key === storageKey || event.key === null) setTheme(event.newValue === 'light' ? 'light' : 'dark')
    }
    window.addEventListener('storage', sync)
    return () => window.removeEventListener('storage', sync)
  }, [])
  return <ThemeContext.Provider value={{theme, toggle: () => setTheme(current => current === 'dark' ? 'light' : 'dark')}}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('ThemeProvider is required')
  return context
}

export function ThemeToggle() {
  const {theme, toggle} = useTheme()
  const label = theme === 'dark' ? '切换到浅色模式' : '切换到深色模式'
  return <button type="button" className="theme-toggle" aria-label={label} title={label} onClick={toggle}>
    {theme === 'dark' ? <Sun size={16}/> : <Moon size={16}/>}<span>{theme === 'dark' ? '浅色模式' : '深色模式'}</span>
  </button>
}
