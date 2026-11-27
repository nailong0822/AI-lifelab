import { Component, Suspense, lazy, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Pause, Play, Orbit } from 'lucide-react'
import { useTheme } from '../ThemeProvider'

const CabinScene = lazy(() => import('./StationScene'))

class SceneBoundary extends Component<{children: ReactNode; failed: () => void}, {failed: boolean}> {
  state = {failed: false}
  static getDerivedStateFromError() { return {failed: true} }
  componentDidCatch() { this.props.failed() }
  render() { return this.state.failed ? null : this.props.children }
}

function supportsScene() {
  try {
    const nav = navigator as Navigator & {deviceMemory?: number; connection?: {saveData?: boolean}}
    if (nav.connection?.saveData || (nav.deviceMemory && nav.deviceMemory < 4)) return false
    const canvas = document.createElement('canvas')
    const gl = canvas.getContext('webgl2', {failIfMajorPerformanceCaveat: true})
    if (!gl) return false
    gl.getExtension('WEBGL_lose_context')?.loseContext()
    return true
  } catch { return false }
}

export default function StationEnvironment({focused, sending}: {focused: boolean; sending: boolean}) {
  const {theme} = useTheme()
  const [capable] = useState(supportsScene)
  const [failed, setFailed] = useState(false)
  const [ready, setReady] = useState(false)
  const [reduced, setReduced] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [staticMode, setStaticMode] = useState(false)
  const [visible, setVisible] = useState(!document.hidden)
  const host = useRef<HTMLDivElement>(null)
  const animate = !staticMode && !reduced && visible
  useEffect(() => {
    const preference = matchMedia('(prefers-reduced-motion: reduce)')
    const updateMotion = () => setReduced(preference.matches)
    let onScreen = true
    const updateVisibility = () => setVisible(!document.hidden && onScreen)
    const observer = new IntersectionObserver(([entry]) => {onScreen = entry.isIntersecting; updateVisibility()})
    if (host.current) observer.observe(host.current)
    preference.addEventListener('change', updateMotion)
    document.addEventListener('visibilitychange', updateVisibility)
    return () => {observer.disconnect(); preference.removeEventListener('change', updateMotion); document.removeEventListener('visibilitychange', updateVisibility)}
  }, [])
  const useScene = capable && !failed && !staticMode
  return <>
    <div ref={host} className={'station-environment' + (useScene && ready ? ' scene-ready' : '') + (animate ? ' is-animated' : '') + (focused ? ' is-focused' : '') + (sending ? ' is-sending' : '')} aria-hidden="true" data-renderer={useScene ? 'webgl' : 'static'}>
      <div className="station-static-cabin"/>
      {useScene && <SceneBoundary failed={() => setFailed(true)}><Suspense fallback={null}><CabinScene light={theme === 'light'} animate={animate} focused={focused} sending={sending} onReady={() => setReady(true)} onFailure={() => setFailed(true)}/></Suspense></SceneBoundary>}
      <div className="station-cabin-grade"/>
      <div className="station-air-dust">{Array.from({length:46}, (_,i) => <i key={i} style={{left:`${(i*37.71+3)%100}%`,top:`${(i*29.19+7)%100}%`,width:i%9===0?'4px':i%3===0?'2.5px':'1.4px',height:i%9===0?'4px':i%3===0?'2.5px':'1.4px',animationDelay:`-${i*.83}s`,animationDuration:`${12+i%7}s`}}/>)}</div>
      <div className="station-window-glare"/>
    </div>
    <div className="station-scene-control"><span><Orbit size={12}/>观景舱</span><button type="button" aria-pressed={!animate} aria-label={staticMode ? '启用动态空间站场景' : '切换为静态空间站场景'} onClick={() => {setStaticMode(value => !value); setReady(false)}} disabled={!capable || failed}>
      {animate ? <Pause size={11}/> : <Play size={11}/>}{!capable || failed ? '静态场景' : reduced && !staticMode ? '减少动态' : staticMode ? '静态场景' : '动态场景'}
    </button></div>
  </>
}
