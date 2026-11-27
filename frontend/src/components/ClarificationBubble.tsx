import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Sparkles, X } from 'lucide-react'
import './clarification-bubble.css'

const title='请补充一些信息,让探索更贴近你'
const description='这些信息会帮助确定检索方向，暂不确定也可以直接写下来'
const shown=new Set<string>()
function wasShown(key:string) {
  try {return shown.has(key)||sessionStorage.getItem('lifelab-clarification:'+key)==='1'} catch {return shown.has(key)}
}

/** A reminder attached to one clarification request, rather than each polling update. */
export function ClarificationBubble({requestKey,onFill}: {requestKey:string;onFill:()=>void}) {
  const [visible,setVisible]=useState(()=>!wasShown(requestKey))
  const [burst,setBurst]=useState(false)
  const flight=useRef<HTMLDivElement>(null)
  const dismiss=useRef<(fill?:boolean)=>void>(()=>{})
  const fill=useRef(onFill)
  fill.current=onFill
  useEffect(()=>{
    if(!visible)return
    let animation:Animation|undefined,readTimer:ReturnType<typeof setTimeout>|undefined,endTimer:ReturnType<typeof setTimeout>|undefined
    let popping=false,disposed=false,started=false,frame=0
    const motion=matchMedia('(prefers-reduced-motion: reduce)')
    const center=()=>`translate3d(${innerWidth/2}px,${innerHeight*.46}px,0) translate(-50%,-50%)`
    const pop=(focusForm=false)=>{
      if(popping||disposed)return
      popping=true;clearTimeout(readTimer);setBurst(true)
      endTimer=setTimeout(()=>{if(disposed)return;setVisible(false);if(focusForm)fill.current()},motion.matches?120:560)
    }
    dismiss.current=pop
    // Defer the once-only marker until the committed frame, including StrictMode remounts.
    const begin=()=>{
      if(document.hidden||started||disposed)return
      started=true
      frame=requestAnimationFrame(()=>{
      if(document.hidden){started=false;return}
      if(wasShown(requestKey)){setVisible(false);return}
      shown.add(requestKey)
      try {sessionStorage.setItem('lifelab-clarification:'+requestKey,'1')} catch { /* In-memory deduplication still applies. */ }
      const element=flight.current
      if(!element)return
      element.style.transform=center()
      const anchor=document.querySelector<HTMLElement>('[data-companion-anchor]')
      const mascot=anchor?.querySelector('img')?.getBoundingClientRect()
      const rect=mascot?.width?mascot:anchor?.getBoundingClientRect()
      const fromX=rect?rect.left+rect.width*.32:innerWidth-80
      const fromY=rect?rect.top+rect.height*.2:innerHeight-140
      const endX=innerWidth/2,endY=innerHeight*.46
      const duration=motion.matches?160:1450
      if(typeof element.animate==='function')animation=element.animate(motion.matches?[
        {opacity:0},{opacity:1},
      ]:[
        {transform:`translate3d(${fromX}px,${fromY}px,0) translate(-50%,-50%) scale(.12) rotate(-12deg)`,opacity:0,offset:0},
        {transform:`translate3d(${fromX-22}px,${fromY-72}px,0) translate(-50%,-50%) scale(.35) rotate(-7deg)`,opacity:1,offset:.18},
        {transform:`translate3d(${endX+(fromX-endX)*.22}px,${endY+28}px,0) translate(-50%,-50%) scale(.86) rotate(3deg)`,opacity:1,offset:.68},
        {transform:`translate3d(${endX}px,${endY-9}px,0) translate(-50%,-50%) scale(1.025) rotate(-1deg)`,opacity:1,offset:.88},
        {transform:center()+' scale(1) rotate(0deg)',opacity:1,offset:1},
      ],{duration,easing:'cubic-bezier(.2,.65,.28,1)',fill:'both'})
      else element.style.opacity='1'
      readTimer=setTimeout(()=>pop(),duration+3800)
      })
    }
    begin()
    const recenter=()=>{animation?.cancel();if(flight.current){flight.current.style.transform=center();flight.current.style.opacity='1'}}
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'&&!event.defaultPrevented)pop()}
    const motionChanged=()=>{if(motion.matches)recenter()}
    window.addEventListener('resize',recenter)
    window.addEventListener('keydown',escape)
    document.addEventListener('visibilitychange',begin)
    motion.addEventListener('change',motionChanged)
    return()=>{disposed=true;cancelAnimationFrame(frame);animation?.cancel();clearTimeout(readTimer);clearTimeout(endTimer);window.removeEventListener('resize',recenter);window.removeEventListener('keydown',escape);document.removeEventListener('visibilitychange',begin);motion.removeEventListener('change',motionChanged);dismiss.current=()=>{}}
  },[requestKey,visible])
  if(!visible)return null
  return createPortal(<div className={'companion-clarification-notice'+(burst?' is-bursting':'')}>
    <span className="clarify-notice-announcement" role="status">奶龙提醒：{title}。{description}。</span>
    <div className="clarify-notice-flight" ref={flight}>
      <button type="button" className="clarify-notice-bubble" onClick={()=>dismiss.current(true)} aria-label="关闭奶龙提醒，填写补充信息">
        <span className="clarify-notice-gloss" aria-hidden="true"/>
        <span className="clarify-notice-spark" aria-hidden="true"><Sparkles size={20}/></span>
        <strong>{title}</strong><span className="clarify-notice-description">{description}</span>
        <X className="clarify-notice-close" size={15} aria-hidden="true"/>
      </button>
      <div className="clarify-notice-explosion" aria-hidden="true"><span className="clarify-notice-ripple"/>{Array.from({length:16},(_,i)=>{
        const angle=i*Math.PI*2/16,radius=140+(i%3)*35
        return <i key={i} style={{'--burst-x':Math.cos(angle)*radius+'px','--burst-y':Math.sin(angle)*radius*.65+'px','--burst-size':6+i%4*3+'px','--burst-hue':i%2?'#b7a4ff':'#8fe8eb'} as React.CSSProperties}/>
      })}</div>
    </div>
  </div>,document.body)
}
