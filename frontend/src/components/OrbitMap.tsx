import { useEffect, useId, useRef, useState } from 'react'
import { Check, CircleHelp, LockKeyhole, Pause, Play, Radio, Sparkles } from 'lucide-react'
import type { PathRun, PathTask, Stage } from '../pathTypes'
import { planetImage } from '../pathGraphics'
import './orbit-map.css'

const states: Record<string, string> = {pending:'待开始', in_progress:'进行中', blocked:'遇到困难', completed:'已完成', skipped:'已跳过'}
type Artifact = 'probe' | 'crystal' | 'station' | 'observatory' | 'relay' | 'capsule'
const names: Record<Artifact, string> = {probe:'探测卫星', crystal:'能量晶体', station:'空间站模块', observatory:'观测装置', relay:'通讯卫星', capsule:'记录舱'}
const worlds = ['潮汐花园', '紫罗兰环', '极昼冰原', '月海档案', '赤砂之境']

function artifactFor(task: PathTask): Artifact {
  // Title has priority: shared descriptions should not make every object identical.
  for (const text of [task.title, task.description + ' ' + task.skills.join(' ')]) {
    if (/投递|面试|联系|沟通|寻求|反馈|交流/.test(text)) return 'relay'
    if (/复盘|总结|整理|清单|日志|记录|归档/.test(text)) return 'capsule'
    if (/学习|课程|语法|掌握|知识|阅读|练习/.test(text)) return 'crystal'
    if (/查询|查阅|搜集|收集|政策|调研|检索|搜寻/.test(text)) return 'probe'
    if (/测试|验证|核验|对比|复现|排查|实验/.test(text)) return 'observatory'
    if (/项目|开发|编写|搭建|制作|实现|作品|代码/.test(text)) return 'station'
  }
  return 'probe'
}

/** Purpose-built miniature objects, sharing metal, glass and energy materials. */
export function OrbitArtifact({kind}: {kind: Artifact}) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, '')
  const fill = `url(#metal${id})`, glass = `url(#glass${id})`
  return <svg viewBox="0 0 96 96" className={'artifact-art artifact-' + kind} aria-hidden="true"><defs>
    <linearGradient id={'metal'+id} x1="0" y1="0" x2="1" y2="1"><stop stopColor="#f0f2e5"/><stop offset=".45" stopColor="#a9bec3"/><stop offset="1" stopColor="#4e667d"/></linearGradient>
    <linearGradient id={'glass'+id} x1="0" y1="0" x2="1" y2="1"><stop stopColor="#a5dddd"/><stop offset=".5" stopColor="#537d9b"/><stop offset="1" stopColor="#283e65"/></linearGradient>
  </defs><ellipse cx="48" cy="80" rx="25" ry="4" className="artifact-ground"/>
    {(kind === 'probe' || kind === 'relay') && <g transform={kind === 'relay' ? 'rotate(-13 48 48)' : 'rotate(17 48 48)'}>
      <path d="M29 46H67" stroke="#a8c6cb" strokeWidth="4"/>
      <g className="artifact-wing wing-left"><path d="M4 32L29 35V61L4 58Z" fill={glass} stroke="#92b5c2"/><path d="M12 33V59M21 34V60M5 41L28 44M5 49L28 52" fill="none" stroke="#c3dbe2" strokeWidth=".8" opacity=".6"/></g>
      <g className="artifact-wing wing-right"><path d="M67 35L92 32V58L67 61Z" fill={glass} stroke="#92b5c2"/><path d="M75 34V60M83 33V59M68 44L91 41M68 52L91 49" fill="none" stroke="#c3dbe2" strokeWidth=".8" opacity=".6"/></g>
      <path d="M35 32L48 27 61 34V64L48 70 35 62Z" fill={fill} stroke="#73909e"/>
      <path d="M48 28V68M36 35L48 41 60 35" fill="none" stroke="#f5f5db" strokeOpacity=".6"/>
      <circle cx="48" cy="53" r="5" fill={glass}/><circle cx="48" cy="53" r="2" className="artifact-light"/>
      {kind === 'relay' ? <><path d="M49 29L55 15M42 14Q53 30 68 19Z" fill={fill} stroke="#8aaab6"/><path className="artifact-signal" d="M62 10Q73 12 75 22M66 4Q81 7 83 22" fill="none" strokeWidth="2"/></> : <><path d="M42 30L40 19M37 19H44" stroke="#adc2c5" strokeWidth="2"/><circle cx="40" cy="17" r="2" className="artifact-light"/></>}
    </g>}
    {kind === 'crystal' && <><ellipse cx="48" cy="73" rx="23" ry="7" fill={fill}/><ellipse cx="48" cy="71" rx="20" ry="5" fill={glass}/><g className="artifact-core"><path d="M48 9L68 34 62 61 48 72 31 57 28 33Z" fill={glass} stroke="#bde7e3"/><path d="M48 9L43 36 48 72 57 35Z" fill="#c0f4ed" opacity=".65"/><path d="M28 33L43 36 68 34M31 57L43 36 62 61" fill="none" stroke="#cff3ef" opacity=".6"/></g><path className="artifact-signal" d="M16 38V46M12 42H20M78 20V28M74 24H82" fill="none" strokeWidth="1.5"/></>}
    {kind === 'station' && <g transform="rotate(-12 48 48)"><path d="M14 53H81M48 23V72" stroke="#9cb9c4" strokeWidth="5"/><g className="artifact-wing wing-left"><path d="M4 30H28V48H4Z" fill={glass} stroke="#adcbd5"/><path d="M12 31V47M20 31V47M5 39H27" stroke="#b5d4df" strokeWidth=".8"/></g><g className="artifact-wing wing-right"><path d="M68 30H92V48H68Z" fill={glass} stroke="#adcbd5"/><path d="M76 31V47M84 31V47M69 39H91" stroke="#b5d4df" strokeWidth=".8"/></g><path d="M34 35L48 28 62 35V64L48 72 34 64Z" fill={fill} stroke="#7998a8"/><path d="M35 36L48 43 61 36M48 43V70" fill="none" stroke="#e3efe6"/><path d="M40 16L48 12 56 16V29L48 33 40 29Z" fill={fill}/><g className="artifact-module"><path d="M13 50L31 44 36 51V66L18 71 13 65Z" fill={fill}/><path d="M61 51L78 45 84 52V66L66 72 61 65Z" fill={fill}/><path d="M17 56L30 52M66 57L78 53" stroke="#516b81" strokeWidth="3"/></g><circle cx="49" cy="53" r="4" className="artifact-light"/></g>}
    {kind === 'observatory' && <><path d="M47 52L26 79M50 51L71 79M49 54V80" stroke="#9bb2bd" strokeWidth="4"/><path d="M32 35L43 23 73 43 61 60Z" fill={fill} stroke="#819eaf"/><ellipse cx="70" cy="48" rx="11" ry="14" transform="rotate(34 70 48)" fill={glass} stroke="#c9e2e3" strokeWidth="3"/><ellipse cx="70" cy="48" rx="5" ry="8" transform="rotate(34 70 48)" className="artifact-light"/><path d="M37 34L31 29 37 22 44 27" fill={glass}/><path className="artifact-signal" d="M75 21L81 15M81 29L90 26" fill="none" strokeWidth="2"/><circle cx="48" cy="57" r="5" fill={fill}/></>}
    {kind === 'capsule' && <g transform="rotate(15 48 48)"><path d="M31 24Q48 11 65 24V70Q48 85 31 70Z" fill={fill} stroke="#92acb6"/><ellipse cx="48" cy="24" rx="17" ry="7" fill="#e0e8de"/><path d="M32 31Q48 39 64 31M32 65Q48 73 64 65" fill="none" stroke="#718c9c" strokeWidth="2"/><rect x="39" y="41" width="18" height="19" rx="3" fill={glass}/><path d="M43 46H53M43 50H53M43 54H49" stroke="#d7efe4" strokeWidth="1.5"/><circle cx="48" cy="73" r="2" className="artifact-light"/></g>}
  </svg>
}

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
    <header className="orbit-scene-header"><div><span>ORBIT / {String(index+1).padStart(2,'0')} · {worlds[index%5]}</span><strong>{current?'当前停靠':'阶段预览'} · {stage.title}</strong></div><button className="orbit-motion-toggle" onClick={()=>setPaused(!paused)} aria-label={paused?'继续轨道动画':'暂停轨道动画'} aria-pressed={paused}>{paused?<Play size={12}/>:<Pause size={12}/>}<span>{paused?'已静止':'慢速巡航'}</span></button></header>
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
        <button className="orbit-object-button" onClick={()=>selectTask(task.id)} title={`${task.title} · ${states[status]}`} aria-label={`行动${i+1}：${task.title}，${states[status]}，${names[kind]}${locked?'，需先完成前置任务':''}`} aria-pressed={selectedTaskId===task.id}>
          <span className="artifact-radiance"/><span className="artifact-visual"><OrbitArtifact kind={kind}/></span><span className="artifact-number">{status==='completed'?<Check size={10}/>:locked?<LockKeyhole size={10}/>:String(i+1).padStart(2,'0')}</span>
          <strong>{task.title}</strong><small><i/>{states[status]} · {names[kind]}</small>
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
