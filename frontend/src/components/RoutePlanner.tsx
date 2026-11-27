import { useState } from 'react'
import { Check, GitCompareArrows, MessageCircle, Rocket } from 'lucide-react'
import type { Basis, Candidate } from '../pathTypes'
import { FlightPlanet } from './FlightPlanet'

const labels={case:'案例证据',synthesis:'综合建议',hypothesis:'待验证假设'}
export function RoutePlanner({candidates,busy,choose,evidence,onChat}: {candidates:Candidate[];busy:boolean;choose:(id:string)=>void;evidence:(basis:Basis)=>void;onChat:()=>void}) {
  const [selected,setSelected]=useState('')
  const [compare,setCompare]=useState(false)
  const candidate=candidates.find(item=>item.id===selected)||candidates[0]
  const markers=candidates.map((item,index)=>({x:100*(index+1)/(candidates.length+1),y:26+Math.abs(index-(candidates.length-1)/2)*13,index,selected:item.id===candidate?.id}))
  if(!candidate)return <p>航线正在准备中。</p>
  return <section className="route-planner">
    <div className="route-planner-toolbar"><div><span className="flight-eyebrow">选择你的下一种可能</span><h2>目的地，由你决定。</h2></div><button aria-pressed={compare} onClick={()=>setCompare(!compare)}><GitCompareArrows size={16}/>{compare?'收起对比':'对比航线'}</button></div>
    <div className="route-planner-grid"><div className="route-cosmos">
      <FlightPlanet index={0} markers={markers}/>
      <svg className="route-trajectories" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">{markers.map((point,i)=><path key={i} d={`M 50 83 Q ${point.x} 68 ${point.x} ${point.y}`} className={point.selected?'selected':''}/>)}</svg>
      {markers.map((point,index)=><button key={candidates[index].id} className={'route-destination'+(point.selected?' selected':'')} style={{left:point.x+'%',top:point.y+'%'}} onClick={()=>setSelected(candidates[index].id)} aria-pressed={point.selected}><span className="route-target"/><strong>{candidates[index].title}</strong><small>{labels[candidates[index].basis.kind]}</small></button>)}
      <div className="route-origin"><span/><strong>你的出发点</strong></div>
      <button className="route-buddy" onClick={onChat} aria-label="和奶龙聊聊探索方向"><img src="/mascot/nailoong-astronaut.png" alt=""/><span><MessageCircle size={14}/>拿不定主意？聊聊</span></button>
    </div><article className="route-brief" key={candidate.id}><button className="basis-chip" onClick={()=>evidence(candidate.basis)}>{labels[candidate.basis.kind]}</button><h3>{candidate.title}</h3><p className="route-brief-goal">{candidate.goal}</p><dl><dt>怎么出发</dt><dd>{candidate.approach}</dd><dt>适合条件</dt><dd>{candidate.suitable_conditions.join('；')||'结合你的实际情况判断'}</dd><dt>预计投入</dt><dd>{candidate.effort}</dd><dt>需要面对</dt><dd>{candidate.difficulties.join('；')||'先通过行动验证'}</dd></dl><div className="route-first-step"><Check size={17}/><div><small>第一步就做这件事</small><p>{candidate.first_action}</p></div></div><button className="space-primary" disabled={busy} onClick={()=>choose(candidate.id)}><Rocket size={17}/>选择这条航线</button></article></div>
    {compare&&<div className="route-comparison" tabIndex={0} role="region" aria-label="航线对比"><table><caption>投入、适合条件与依据</caption><thead><tr><th scope="col">航线</th><th scope="col">投入</th><th scope="col">适合条件</th><th scope="col">规划依据</th></tr></thead><tbody>{candidates.map(item=><tr key={item.id}><th scope="row">{item.title}</th><td>{item.effort}</td><td>{item.suitable_conditions.join('；')}</td><td><button onClick={()=>evidence(item.basis)}>{labels[item.basis.kind]}</button></td></tr>)}</tbody></table></div>}
  </section>
}
