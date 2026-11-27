import { useEffect, useRef, useState } from 'react'
import { Check, Circle, MessageCircle, Pause, Play, Star } from 'lucide-react'
import type { PathRun, Stage } from '../pathTypes'
import type { JourneyReward } from '../useJourneyRewards'
import { FlightPlanet } from './FlightPlanet'
import { artifactFor, OrbitArtifact } from './OrbitArtifact'

export function StageRail({stages,currentId,selectedId,done,select}: {stages:Stage[];currentId:string|null;selectedId:string;done:(stage:Stage)=>boolean;select:(stage:Stage)=>void}) {
  return <nav className="flight-stage-rail" aria-label="探索阶段">{stages.map((stage,index)=><button key={stage.id} className={(selectedId===stage.id?' selected':'')+(done(stage)?' completed':'')} onClick={()=>select(stage)} aria-current={selectedId===stage.id?'step':undefined}><span className="stage-rail-node">{done(stage)?<Check size={16}/>:String(index+1).padStart(2,'0')}</span><span><strong>{stage.title}</strong><small>{done(stage)?'已抵达':stage.id===currentId?'正在探索':'待探索'}</small></span></button>)}</nav>
}

function positions(count:number) {
  const presets:Record<number,number[][]>={1:[[44,15]],2:[[19,28],[73,30]],3:[[20,24],[72,24],[22,72]],4:[[20,24],[72,24],[20,69],[55,80]]}
  return presets[count]||Array.from({length:count},(_,i)=>{const angle=(-110+i*290/Math.max(1,count-1))*Math.PI/180;return [44+35*Math.cos(angle),47+34*Math.sin(angle)]})
}
export function JourneyViewport({stage,index,progress,selectedTaskId,selectTask,onChat,rewards,consume,totalStars,collectedStars}: {stage:Stage;index:number;progress:PathRun['progress'];selectedTaskId:string;selectTask:(id:string)=>void;onChat:()=>void;rewards:JourneyReward[];consume:(id:string)=>void;totalStars:number;collectedStars:number}) {
  const host=useRef<HTMLDivElement>(null)
  const flying=useRef<HTMLSpanElement>(null)
  const [paused,setPaused]=useState(false)
  const [impact,setImpact]=useState('')
  const [announcement,setAnnouncement]=useState('')
  const reward=rewards[0]
  const points=positions(stage.tasks.length)
  useEffect(()=>{
    if(!reward)return
    const targetIndex=stage.tasks.findIndex(task=>task.id===reward.taskId)
    if(reward.stageId!==stage.id||targetIndex<0||matchMedia('(prefers-reduced-motion: reduce)').matches||!host.current||!flying.current||typeof flying.current.animate!=='function'){consume(reward.id);return}
    const rect=host.current.getBoundingClientRect()
    const target=positions(stage.tasks.length)[targetIndex]
    const start=[rect.width*.79,rect.height*.69],end=[rect.width*target[0]/100,rect.height*target[1]/100]
    const frames=Array.from({length:61},(_,i)=>{
      const t=i/60,out=t<.48,u=out?t/.48:(t-.48)/.52
      const a=out?start:end,b=out?end:start
      const x=(1-u)*a[0]+u*b[0],y=(1-u)*a[1]+u*b[1]-Math.sin(u*Math.PI)*(out?85:45)
      return {transform:`translate(${x}px,${y}px) translate(-50%,-50%) rotate(${t*540}deg) scale(${.6+Math.sin(t*Math.PI)*.65})`,opacity:i===0||i===60?0:1,offset:t}
    })
    const animation=flying.current.animate(frames,{duration:2400,easing:'linear',fill:'both'})
    const hit=setTimeout(()=>{setImpact(reward.taskId);setAnnouncement(`已完成「${reward.title}」，奶龙为你收集了一颗星星。`)},1120)
    animation.onfinish=()=>{setImpact('');consume(reward.id)}
    return()=>{clearTimeout(hit);animation.cancel();setImpact('')}
  },[reward?.id,stage.id,consume])
  const pending=new Set(rewards.filter(item=>item.stageId===stage.id&&item.taskId!==impact).map(item=>item.taskId))
  return <div ref={host} className={'planet-orbit-scene flight-viewport'+(paused?' is-paused':'')}>
    <div className="flight-scene-heading"><div><span className="flight-eyebrow">正在观测</span><strong>{stage.title}</strong></div><button aria-pressed={paused} aria-label={paused?'恢复星球动画':'暂停星球动画'} onClick={()=>setPaused(!paused)}>{paused?<Play size={15}/>:<Pause size={15}/>}</button></div>
    <div className="flight-dust" aria-hidden="true"/>
    <FlightPlanet index={index} paused={paused}/>
    <svg className="flight-orbits" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><ellipse cx="44" cy="47" rx="36" ry="33"/><ellipse cx="44" cy="47" rx="28" ry="25"/></svg>
    {stage.tasks.map((task,i)=>{
      const status=progress[stage.id+':'+task.id]?.status||'pending'
      const lit=status==='completed'&&!pending.has(task.id)
      return <button key={task.id} className={'flight-artifact'+(lit?' is-lit':'')+(selectedTaskId===task.id?' selected':'')+(impact===task.id?' is-igniting':'')} style={{left:points[i][0]+'%',top:points[i][1]+'%'}} onClick={()=>selectTask(task.id)} aria-label={`行动 ${i+1}：${task.title}，${status==='completed'?'已完成':status==='skipped'?'已跳过':'待完成'}`} aria-pressed={selectedTaskId===task.id} title={task.title}><OrbitArtifact kind={artifactFor(task)}/><span className="flight-artifact-index">{lit?<Star size={12} fill="currentColor"/>:<Circle size={10}/>} {String(i+1).padStart(2,'0')}</span></button>
    })}
    {!stage.tasks.length&&<p className="flight-unexplored">这颗星球等待你的抵达<br/><small>展开这一站后，会出现行动物件。</small></p>}
    <div className={'flight-buddy-zone'+(reward?.stageId===stage.id?' is-summoning':'')}><div className="buddy-star-orbits" aria-hidden="true">{Array.from({length:collectedStars},(_,i)=>{const ring=Math.floor(i/8),angle=(i%8)*45+(ring%2)*22.5;return <span className="buddy-collected-star" key={i} style={{'--star-angle':angle+'deg','--star-radius':(52+ring*15)+'px','--star-delay':(-i*1.3)+'s'} as React.CSSProperties}><Star size={ring>1?10:13} fill="currentColor"/></span>})}</div><button className="flight-buddy" onClick={onChat} aria-label="和随航伙伴奶龙聊天"><img src="/mascot/nailoong-astronaut.png" alt="" draggable={false}/><span><MessageCircle size={14}/>和奶龙聊聊</span></button></div>
    <div className="flight-scene-footer"><span><Star size={15} fill="currentColor"/><strong>{totalStars}</strong> 颗行动之星</span><small>完成行动，为探索添一束光</small></div>
    <span className="flight-reward-star" ref={flying} aria-hidden="true"><Star size={32} fill="currentColor"/></span>
    <span className="sr-only" role="status">{announcement}</span>
  </div>
}
