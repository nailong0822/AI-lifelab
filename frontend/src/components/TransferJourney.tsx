import {useEffect,useId,useRef,useState} from 'react'
import {createPortal} from 'react-dom'
import {Check,Navigation,Sparkles} from 'lucide-react'
import type {JourneyTransfer} from '../journeyTransfer'
import {planetTheme,techPlanetImage} from '../techPlanets'
import './transfer-journey.css'

function TransferPod(){
  const id=useId().replace(/[^a-zA-Z0-9]/g,'')
  return <svg viewBox="0 0 240 300" className="transfer-pod" aria-hidden="true"><defs>
    <linearGradient id={id+'metal'} x1="0" y1="0" x2="1" y2="1"><stop stopColor="#f1f7fb"/><stop offset=".3" stopColor="#a6c6d4"/><stop offset=".56" stopColor="#e2edf2"/><stop offset="1" stopColor="#3e607a"/></linearGradient>
    <linearGradient id={id+'glass'} x1="0" y1="0" x2="1" y2="1"><stop stopColor="#8adff5" stopOpacity=".32"/><stop offset=".45" stopColor="#305e86" stopOpacity=".08"/><stop offset="1" stopColor="#a1d4ed" stopOpacity=".32"/></linearGradient>
    <linearGradient id={id+'jet'} x1="0" y1="0" x2="0" y2="1"><stop stopColor="#e5ffff"/><stop offset=".3" stopColor="#80f4f3" stopOpacity=".85"/><stop offset="1" stopColor="#66aaff" stopOpacity="0"/></linearGradient>
    <clipPath id={id+'window'}><path d="M120 42C80 42 62 82 62 134V196Q120 226 178 196V134C178 82 160 42 120 42Z"/></clipPath>
  </defs>
    <g className="transfer-pod-thrust"><path d="M72 228Q64 264 81 298Q99 267 91 228Z" fill={'url(#'+id+'jet)'}/><path d="M149 228Q140 270 159 298Q177 265 168 228Z" fill={'url(#'+id+'jet)'}/></g>
    <path d="M56 149L31 184 33 226 59 210M184 149L209 184 207 226 181 210" fill={'url(#'+id+'metal)'} stroke="#9fbecb"/>
    <path d="M120 25C65 25 44 79 44 134V205C44 253 196 253 196 205V134C196 79 175 25 120 25Z" fill={'url(#'+id+'metal)'} stroke="#deeff8" strokeWidth="1.5"/>
    <path d="M120 36C73 36 54 82 54 134V200Q120 240 186 200V134C186 82 167 36 120 36Z" fill="#10263d" stroke="#528ba3" strokeWidth="2"/>
    <g clipPath={'url(#'+id+'window)'}><image className="transfer-pod-passenger" href="/mascot/nailoong-astronaut.png" x="53" y="52" width="134" height="156" preserveAspectRatio="xMidYMid meet"/><path d="M120 42C80 42 62 82 62 134V196Q120 226 178 196V134C178 82 160 42 120 42Z" fill={'url(#'+id+'glass)'}/><path d="M76 83Q84 60 104 55M70 103L68 128" stroke="#e4ffff" strokeOpacity=".7" strokeWidth="3" strokeLinecap="round" fill="none"/></g>
    <g className="transfer-pod-door door-left"><path d="M53 130V200Q78 216 119 219V139" fill="#8be9f5" fillOpacity=".055" stroke="#b2efff" strokeOpacity=".24"/></g><g className="transfer-pod-door door-right"><path d="M187 130V200Q162 216 121 219V139" fill="#8be9f5" fillOpacity=".055" stroke="#b2efff" strokeOpacity=".24"/></g>
    <path d="M51 203Q120 242 189 203L185 220Q120 254 55 220Z" fill={'url(#'+id+'metal)'} stroke="#91b6c7"/>
    <path d="M58 216Q120 246 182 216" fill="none" stroke="#83f7ed" strokeWidth="3" className="transfer-pod-energy"/>
    <rect x="101" y="226" width="38" height="12" rx="6" fill="#264960" stroke="#8dc5d0"/><circle cx="113" cy="232" r="2" fill="#92ffdc"/><circle cx="121" cy="232" r="2" fill="#92ffdc"/><circle cx="129" cy="232" r="2" fill="#92ffdc"/>
    <path d="M102 30Q120 21 138 30" fill="none" stroke="#aeffff" strokeWidth="3"/>
  </svg>
}

export function TransferJourney({transfer,finish}: {transfer:JourneyTransfer;finish:(id:string)=>void}){
  const dialog=useRef<HTMLDialogElement>(null)
  const [reduced,setReduced]=useState(()=>matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [phase,setPhase]=useState<'boarding'|'cruise'|'arrival'>(reduced?'arrival':'boarding')
  useEffect(()=>{
    const element=dialog.current!
    const previous=document.activeElement as HTMLElement|null
    element.showModal()
    const timers:ReturnType<typeof setTimeout>[]=[]
    if(!reduced){timers.push(setTimeout(()=>setPhase('cruise'),950),setTimeout(()=>setPhase('arrival'),2700))}
    timers.push(setTimeout(()=>finish(transfer.id),reduced?750:3650))
    const media=matchMedia('(prefers-reduced-motion: reduce)')
    const change=()=>{if(media.matches){setReduced(true);finish(transfer.id)}}
    const hidden=()=>{if(document.hidden)finish(transfer.id)}
    media.addEventListener('change',change);document.addEventListener('visibilitychange',hidden)
    return()=>{timers.forEach(clearTimeout);media.removeEventListener('change',change);document.removeEventListener('visibilitychange',hidden);element.close();if(previous?.isConnected)previous.focus({preventScroll:true})}
  },[transfer.id,finish])
  const labels={boarding:'奶龙正在登舱',cruise:'穿越星轨，前往新的坐标',arrival:'已抵达，继续你的探索'}
  return createPortal(<dialog ref={dialog} className={'transfer-journey phase-'+phase+(reduced?' reduced-motion':'')} aria-label={transfer.kind==='route'?'奶龙正在切换航线':'奶龙正在前往下一颗星球'} onCancel={event=>{event.preventDefault();finish(transfer.id)}}>
    <div className="transfer-journey-inner" style={{'--transfer-color':planetTheme(transfer.toIndex).light} as React.CSSProperties}>
      <header><span className="transfer-journey-tag"><Navigation size={14}/>{transfer.kind==='route'?'切换探索航线':'前往下一颗星球'}</span><h2>{transfer.toTitle}</h2><p role="status">{labels[phase]}</p></header>
      <div className="transfer-space" aria-hidden="true">
        <div className="transfer-warp">{Array.from({length:24},(_,i)=><i key={i} style={{'--ray-angle':i*15+'deg','--ray-delay':-(i%7)*.15+'s','--ray-distance':120+(i%5)*30+'px'} as React.CSSProperties}/>)}</div>
        <div className="transfer-world world-from"><img src={techPlanetImage(transfer.fromIndex)} alt=""/><span>{transfer.fromTitle}</span></div>
        <div className="transfer-world world-to"><img src={techPlanetImage(transfer.toIndex)} alt=""/><span>{transfer.destinationStage}</span></div>
        <svg className="transfer-flight-path" viewBox="0 0 1000 400" preserveAspectRatio="none"><path d="M160 280Q370 310 500 185T850 140"/><path className="transfer-path-light" d="M160 280Q370 310 500 185T850 140"/></svg>
        <div className="transfer-traveler"><div className="transfer-craft"><TransferPod/></div></div>
        <img className="transfer-boarding-mascot" src="/mascot/nailoong-astronaut.png" alt=""/>
        <div className="transfer-arrival-ring"/>
      </div>
      <footer><span>{phase==='arrival'?<Check size={16}/>:<Sparkles size={16}/>} {transfer.kind==='route'?'新的航线已经准备好':'一步步，把可能变成经历'}</span><button autoFocus onClick={()=>finish(transfer.id)}>跳过动画</button></footer>
    </div>
  </dialog>,document.body)
}
