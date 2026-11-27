import { useEffect, useRef, useState } from 'react'
import { Check, CircleHelp, LockKeyhole, Pause, Play, Radio, Sparkles } from 'lucide-react'
import type { PathRun, PathTask, Stage } from '../pathTypes'
import { planetImage } from '../pathGraphics'
import './orbit-map.css'
import { OrbitArtifact, artifactFor } from './OrbitArtifact'

const states: Record<string, string> = {pending:'待开始', in_progress:'进行中', blocked:'遇到困难', completed:'已完成', skipped:'已跳过'}

function OrbitScene({stage, index, current, complete, progress, selectedTaskId, selectTask, help}: {
  stage: Stage; index: number; current: boolean; complete: boolean; progress: PathRun['progress']; selectedTaskId: string;
  selectTask: (id: string) => void; help: (task: PathTask) => void
}) {
  const scene = useRef<HTMLDivElement>(null)
  const [paused, setPaused] = useState(false)
  const phase = useRef(0)
  const entered = useRef({pointer:false, focus:false})
  const [lit, setLit] = useState<string[]>([])
  const previous = useRef<Record<string,string>>({})
  const statuses = stage.tasks.map(t => progress[stage.id+':'+t.id]?.status || 'pending')
  const signature = statuses.join('|')
  useEffect(() => {
    const next = Object.fromEntries(stage.tasks.map((t,i) => [t.id,statuses[i]]))
    const changed = stage.tasks.filter(t => next[t.id] === 'completed' && previous.current[t.id] && previous.current[t.id] !== 'completed').map(t=>t.id)
    previous.current = next
    setLit(changed)
    const timer = setTimeout(()=>setLit([]),2600)
    return ()=>clearTimeout(timer)
  }, [signature])
  useEffect(() => {
    const root = scene.current!
    const nodes = Array.from(root.querySelectorAll<HTMLElement>('.orbit-object'))
    const reduced = matchMedia('(prefers-reduced-motion: reduce)')
    let frame = 0, last = 0, visible = true
    function draw(time: number) {
      if (last && !entered.current.pointer && !entered.current.focus && !paused && !reduced.matches) phase.current += Math.min(time-last,100) / 165000 * Math.PI*2
      last = time
      nodes.forEach((node,i) => {
        const angle = -.65 + i * Math.PI*2 / nodes.length + phase.current
        node.style.left = (50+35*Math.cos(angle))+'%'
        node.style.top = (53+25*Math.sin(angle))+'%'
        node.classList.toggle('object-north', Math.sin(angle) < -.3)
      })
      if (!document.hidden && visible && !reduced.matches && !paused) frame = requestAnimationFrame(draw)
    }
    function resume() {cancelAnimationFrame(frame);last=0;draw(0)}
    const observer = new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;resume()})
    observer.observe(root)
    document.addEventListener('visibilitychange',resume)
    reduced.addEventListener('change',resume)
    resume()
    return ()=>{cancelAnimationFrame(frame);observer.disconnect();document.removeEventListener('visibilitychange',resume);reduced.removeEventListener('change',resume)}
  }, [stage.id, stage.tasks.length, paused])
  const count = statuses.filter(s=>s==='completed').length
  return <div className={'planet-orbit-scene'+(complete?' orbit-stage-complete':'')} ref={scene}
    onPointerEnter={()=>{entered.current.pointer=true}} onPointerLeave={()=>{entered.current.pointer=false}}
    onFocusCapture={()=>{entered.current.focus=true}} onBlurCapture={e=>{if(!e.currentTarget.contains(e.relatedTarget as Node)) entered.current.focus=false}}>
    <header className="orbit-scene-header"><div><span>ORBIT / {String(index+1).padStart(2,'0')}</span><strong>{current?'当前停靠':'阶段预览'} · {stage.title}</strong></div><button className="orbit-motion-toggle" onClick={()=>setPaused(!paused)} aria-label={paused?'继续轨道动画':'暂停轨道动画'} aria-pressed={paused}>{paused?<Play size={12}/>:<Pause size={12}/>}<span>{paused?'已静止':'慢速巡航'}</span></button></header>
    <svg className="action-orbit-lines" viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true"><ellipse cx="500" cy="530" rx="350" ry="250"/><ellipse cx="500" cy="530" rx="392" ry="285"/><path d="M500 205V235M500 825V855M82 530H112M888 530H918"/></svg>
    {lit.length > 0 && <svg className="artifact-return-signal" viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true">{lit.map(taskId=>{
      const angle = -.65 + stage.tasks.findIndex(t=>t.id===taskId)*Math.PI*2/stage.tasks.length + phase.current
      return <line key={taskId} x1={500+350*Math.cos(angle)} y1={530+250*Math.sin(angle)} x2="500" y2="530" pathLength="100"/>
    })}</svg>}
    <div className="orbit-planet-core" aria-hidden="true"><span className="planet-complete-halo"/><span className="planet-soft-aura"/><img src={planetImage(index+2)} alt=""/><span className="planet-ground-shadow"/></div>

    {stage.tasks.map((task,i)=>{
      const status = statuses[i], kind = artifactFor(task)
      const locked = !task.depends_on.every(id=>['completed','skipped'].includes(progress[stage.id+':'+id]?.status || 'pending'))
      const angle = -.65 + i*Math.PI*2/stage.tasks.length + phase.current
      return <div key={task.id} className={'orbit-object state-'+status+(Math.sin(angle)<-.3?' object-north':'')+(selectedTaskId===task.id?' object-selected':'')+(lit.includes(task.id)?' object-just-lit':'')}
        style={{left:(50+35*Math.cos(angle))+'%',top:(53+25*Math.sin(angle))+'%'}}>
        <button className="orbit-object-button" onClick={()=>selectTask(task.id)} title={`${task.title} · ${states[status]}`} aria-label={`行动${i+1}：${task.title}，${states[status]}${locked?'，需先完成前置任务':''}`} aria-pressed={selectedTaskId===task.id}>
          <span className="artifact-radiance"/><span className="artifact-visual"><OrbitArtifact kind={kind}/></span><span className="artifact-number">{status==='completed'?<Check size={10}/>:locked?<LockKeyhole size={10}/>:String(i+1).padStart(2,'0')}</span>
          <strong>{task.title}</strong><small><i/>{states[status]}</small>
        </button>
        {status==='blocked' && <button className="orbit-help-beacon" aria-label={`向随航伙伴求助：${task.title}`} onClick={()=>help(task)}><CircleHelp size={14}/></button>}
      </div>
    })}
    {!stage.tasks.length && <p className="orbit-no-tasks">{complete?'这一站已保存完成记录。':'先看方向，到站后再搭建你的行动轨道。'}</p>}
    <footer className="orbit-scene-footer"><span><Radio size={12}/>{stage.tasks.length?`${count} / ${stage.tasks.length} 件行动已点亮${complete?' · 可以启程':''}`:complete?'这一站已探索':'抵达后展开行动'}</span><span>悬停或聚焦时停靠</span></footer>
    <span className="sr-only" role="status">{lit.length ? '行动已点亮，轨道物件已展开。' : ''}</span>
  </div>
}

export function OrbitMap({stages,currentId,selectedId,progress,selectedTaskId,select,selectTask,done,help}: {
  stages: Stage[]; currentId: string|null; selectedId: string; progress: PathRun['progress']; selectedTaskId: string;
  select: (stage:Stage)=>void; selectTask:(id:string)=>void; done:(stage:Stage)=>boolean; help:(task:PathTask)=>void
}) {
  const stage = stages.find(s=>s.id===selectedId) || stages[0]
  const index = stages.indexOf(stage)
  return <section className="orbital-explorer" aria-label="阶段星图与行动轨道">
    <OrbitScene key={stage.id} stage={stage} index={index} current={stage.id===currentId} complete={done(stage)} progress={progress} selectedTaskId={selectedTaskId} selectTask={selectTask} help={help}/>
    <div className="orbit-route-heading"><span>你的星际航线</span><small><Sparkles size={11}/>一次，建设一颗星球</small></div>
    <nav className="planet-route-rail" aria-label="选择探索阶段">{stages.map((s,i)=><button key={s.id} className={'planet-route-stop'+(s.id===selectedId?' selected':'')+(done(s)?' explored':'')} aria-label={`${i+1}. ${s.title}，${s.id===currentId?'当前停靠':done(s)?'已探索':'等待探索'}`} aria-pressed={s.id===selectedId} onClick={()=>select(s)}>
      <span className="rail-planet"><img src={planetImage(i+2)} alt=""/>{done(s)&&<i><Check size={10}/></i>}</span><small>{String(i+1).padStart(2,'0')} / {s.id===currentId?'当前坐标':done(s)?'已探索':'未来航程'}</small><strong>{s.title}</strong>
    </button>)}</nav>
  </section>
}
