import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import { CompanionProvider } from './components/CompanionDock'
import { ThemeProvider } from './ThemeProvider'
import { AuthProvider } from './AuthProvider'
import './styles.css'
import './theme.css'
import './theme-modes.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: true },
    mutations: { retry: false },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider><BrowserRouter><AuthProvider><CompanionProvider><App /></CompanionProvider></AuthProvider></BrowserRouter></ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>,
)
