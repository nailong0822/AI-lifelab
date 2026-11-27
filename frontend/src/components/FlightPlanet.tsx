import { Component, Suspense, lazy, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { planetTheme, techPlanetImage } from '../techPlanets'

const PlanetScene=lazy(()=>import('./FlightPlanetScene'))
export interface PlanetMarker {x:number;y:number;index:number;selected?:boolean}

class PlanetBoundary extends Component<{children:ReactNode;fail:()=>void},{failed:boolean}> {
  state={failed:false}
  static getDerivedStateFromError(){return {failed:true}}
  componentDidCatch(){this.props.fail()}
  render(){return this.state.failed?null:this.props.children}
}

export function FlightPlanet({index,paused=false,markers}: {index:number;paused?:boolean;markers?:PlanetMarker[]}) {
  const host=useRef<HTMLDivElement>(null)
  const [ready,setReady]=useState(false)
  const [failed,setFailed]=useState(false)
  const [visible,setVisible]=useState(!document.hidden)
  const [reduced,setReduced]=useState(()=>matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [capable]=useState(()=>{
    try{const nav=navigator as Navigator&{deviceMemory?:number;connection?:{saveData?:boolean}};if(nav.connection?.saveData || (nav.deviceMemory && nav.deviceMemory<4))return false;const gl=document.createElement('canvas').getContext('webgl2',{failIfMajorPerformanceCaveat:true});if(!gl)return false;gl.getExtension('WEBGL_lose_context')?.loseContext();return true}catch{return false}
  })
  useEffect(()=>{
    const motion=matchMedia('(prefers-reduced-motion: reduce)');let inside=true
    const update=()=>setVisible(inside&&!document.hidden)
    const change=()=>setReduced(motion.matches)
    const observer=new IntersectionObserver(([entry])=>{inside=entry.isIntersecting;update()})
    if(host.current)observer.observe(host.current)
    motion.addEventListener('change',change);document.addEventListener('visibilitychange',update)
    return()=>{observer.disconnect();motion.removeEventListener('change',change);document.removeEventListener('visibilitychange',update)}
  },[])
  const points=markers || [{x:44,y:47,index}]
  return <div ref={host} className={'flight-planets'+(ready&&!failed?' is-rendered':'')+(!paused&&!reduced&&visible?' is-animated':'')} aria-hidden="true" data-renderer={capable&&!failed?'webgl':'static'}>
    <div className={'planet-nebula-field'+(markers?' is-route':'')}>{points.map((point,i)=><span key={i} style={{left:point.x+'%',top:point.y+'%','--planet-energy':planetTheme(point.index).light} as React.CSSProperties}/>)}</div>
    <div className="flight-planets-fallback">{points.map((point,i)=><img key={i} src={techPlanetImage(point.index)} alt="" className={markers?'route-planet-fallback':'mission-planet-fallback'} style={{left:point.x+'%',top:point.y+'%'}}/>)}</div>
    {capable&&!failed&&<PlanetBoundary fail={()=>setFailed(true)}><Suspense fallback={null}><PlanetScene index={index} markers={markers} animate={!paused&&!reduced&&visible} ready={()=>setReady(true)} fail={()=>setFailed(true)}/></Suspense></PlanetBoundary>}
  </div>
}
