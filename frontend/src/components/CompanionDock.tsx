import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { matchPath, useLocation } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { LoaderCircle, MessageCircle, X } from 'lucide-react'
import { pathApi } from '../pathApi'
import type { PathRun, PathTask } from '../pathTypes'
import { useAuth } from '../AuthProvider'
import { CompanionPanel } from './CompanionPanel'
import './companion-dock.css'

type TaskContext = {path: PathRun; task?: PathTask; stageId?: string}
const DockContext = createContext<{openCompanion: (context?: TaskContext) => void;isOpen:boolean} | null>(null)
export function useCompanion() {
  const value = useContext(DockContext)
  if (!value) throw new Error('CompanionProvider is required')
  return value
}

export function CompanionProvider({children}: {children: ReactNode}) {
  const location = useLocation()
  const {user, openKey} = useAuth()
  const cache = useQueryClient()
  const [open, setOpen] = useState(false)
  const [personal, setPersonal] = useState(false)
  const [lastPath, setLastPath] = useState<PathRun | null>(null)
  const [taskContext, setTaskContext] = useState<TaskContext | null>(null)
  const [hint, setHint] = useState(true)
  const launcher = useRef<HTMLButtonElement>(null)
  const match = matchPath('/explore/:runId', location.pathname) || matchPath('/retrieval/:runId', location.pathname)
  const runId = match?.params.runId
  const hidden = location.pathname === '/admin' || location.pathname.startsWith('/shared-cases/')
  const home = location.pathname === '/retrieval' || location.pathname === '/'
  const exploring = location.pathname.startsWith('/explore/')
  const lookup = useQuery({queryKey: ['path', runId], queryFn: () => pathApi.lookup(runId!), enabled: !!runId && !hidden})
  const currentPath = runId ? lookup.data?.plan ? lookup.data : null : lastPath
  const path = personal ? null : currentPath
  const task = taskContext?.path.id === path?.id ? taskContext?.task || null : null

  useEffect(() => {setPersonal(false); setTaskContext(null)}, [runId])
  useEffect(() => {if (lookup.data?.plan) setLastPath(lookup.data)}, [lookup.data])
  useEffect(() => {if (hidden) setOpen(false)}, [hidden])
  const refreshPath = () => {
    if (!path) return
    void cache.invalidateQueries({queryKey: ['path', path.retrieval_run_id]})
    void cache.invalidateQueries({queryKey: ['path-entry', path.retrieval_run_id]})
    // Keep the remembered journey fresh when chatting from the homepage.
    if (!runId) void pathApi.lookup(path.retrieval_run_id).then(value => setLastPath(value?.plan ? value : null)).catch(() => {})
  }
  const openCompanion = (context?: TaskContext) => {
    if (context) {
      cache.setQueryData(['path', context.path.retrieval_run_id], context.path)
      setLastPath(context.path); setTaskContext(context); setPersonal(false)
    }
    setHint(false); setOpen(true)
  }
  const close = () => {setOpen(false); requestAnimationFrame(() => launcher.current?.focus())}
  return <DockContext.Provider value={{openCompanion,isOpen:open}}>{children}
    {user && !hidden && <>
      {!home && !exploring && <div className={'companion-dock' + (location.pathname === '/history' ? ' is-archive' : '') + (open ? ' is-chatting' : '')}>
        {hint && !open && <div className="companion-greeting"><span>我在这里，随时聊聊</span><button aria-label="收起伙伴提示" onClick={() => setHint(false)}><X size={12}/></button></div>}
        <button ref={launcher} data-companion-anchor className="companion-launcher" aria-label={open ? '收起随航伙伴' : '与奶龙随航伙伴聊天'} aria-expanded={open} aria-controls="global-companion-panel" onClick={() => open ? close() : openCompanion()}>
          <span className="companion-orbit" aria-hidden="true"/>
          <img src="/mascot/nailoong-astronaut.png" alt="" draggable={false}/>
          <span className="companion-launcher-label"><MessageCircle size={13}/>随航伙伴</span>
        </button>
      </div>}
      {open && runId && lookup.isPending ? <div className="companion-dock-notice" role="status"><LoaderCircle size={16} className="spin"/>正在读取当前航程…<button onClick={close} aria-label="关闭"><X size={16}/></button></div>
        : open && lookup.isError && !personal ? <div className="companion-dock-notice" role="alert">航程暂未载入<button onClick={() => void lookup.refetch()}>重试</button><button onClick={() => setPersonal(true)}>先聊聊</button><button onClick={close} aria-label="关闭"><X size={16}/></button></div>
        : <CompanionPanel key={path?.id || 'personal'} journey={exploring} open={open} path={path} task={task} stageId={taskContext?.stageId} close={close} unlink={() => setTaskContext(null)} refreshPath={refreshPath} contextControls={<div className="buddy-scope-switch">
          <button aria-pressed={!path} onClick={() => {setPersonal(true); setTaskContext(null)}}>日常陪伴</button>
          {currentPath && <button aria-pressed={!!path} onClick={() => setPersonal(false)}>聊聊这条航线</button>}
          {!user.model_configured && <button className="buddy-key-reminder" onClick={openKey}>设置 API Key</button>}
        </div>}/>} 
    </>}
  </DockContext.Provider>
}
