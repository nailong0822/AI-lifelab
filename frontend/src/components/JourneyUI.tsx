import { useState } from 'react'
import { ArrowRight, Check, ChevronDown, Circle, Clock3, LockKeyhole, Sparkles, Star } from 'lucide-react'
import { planetImage } from '../pathGraphics'
import type { Basis, Candidate, PathRun, PathTask, Stage } from '../pathTypes'

const basisLabel = {case: '案例证据', synthesis: '综合建议', hypothesis: '待验证假设'}
const statusLabel: Record<string, string> = {pending: '待开始', in_progress: '进行中', blocked: '遇到困难', completed: '已完成', skipped: '已跳过'}
const tones = ['#92c8ca', '#c4a0e7', '#dcb28b', '#86bfa5']

export function GalaxyCard({candidate, index, busy, choose, evidence}: {candidate: Candidate; index: number; busy: boolean; choose: () => void; evidence: (basis: Basis) => void}) {
  return <article className="route-card" style={{'--galaxy-tone': tones[index % tones.length]} as React.CSSProperties}>
    <div className="galaxy-art" aria-hidden="true"><div className="galaxy-ring g-ring-one"/><div className="galaxy-ring g-ring-two"/><div className="galaxy-ring g-ring-three"/><span className="galaxy-sun"/><img className="galaxy-world" src={planetImage(index + 2)} alt=""/><img className="galaxy-moon" src={planetImage(index)} alt=""/><span className="galaxy-spark"/></div>
    <div className="route-card-content"><div className="route-card-label"><span>航线 {String(index + 1).padStart(2, '0')}</span><button className="basis-chip" onClick={() => evidence(candidate.basis)}>{basisLabel[candidate.basis.kind]} ↗</button></div>
      <h2>{candidate.title}</h2><p className="route-goal">{candidate.goal}</p><div className="route-first-action"><Sparkles size={14}/><div><small>从一个小实验开始</small><p>{candidate.first_action}</p></div></div>
      <details className="route-information"><summary>适合条件、投入与难点<ChevronDown size={14}/></summary><dl><dt>怎么走</dt><dd>{candidate.approach}</dd><dt>适合的条件</dt><dd>{candidate.suitable_conditions.join('；')}</dd><dt>预计投入</dt><dd>{candidate.effort}</dd><dt>可能的困难</dt><dd>{candidate.difficulties.join('；')}</dd></dl></details>
      <button className="space-primary" disabled={busy} onClick={choose}>探索这条航线<ArrowRight size={15}/></button>
    </div>
  </article>
}

export function MissionTasks({stage, run, editable, progress, evidence, help, selectedTaskId, selectTask}: {stage: Stage; run: PathRun; editable: boolean; progress: (task: PathTask, status: string) => Promise<void>; evidence: (basis: Basis) => void; help: (task: PathTask) => void; selectedTaskId: string; selectTask: (id: string | null) => void}) {
  const allowed = editable && run.plan!.stages.findIndex(s => s.id === stage.id) <= run.plan!.stages.findIndex(s => s.id === run.current_stage_id)
  return <div className="mission-task-list">{stage.tasks.map((task, i) => {
    const saved = run.progress[stage.id + ':' + task.id]
    const state = saved?.status || 'pending'
    const unlocked = task.depends_on.every(id => ['completed', 'skipped'].includes(run.progress[stage.id + ':' + id]?.status || 'pending'))
    const open = selectedTaskId === task.id
    return <article className={'space-task task-' + state + (open ? ' is-expanded' : '')} key={task.id}>
      <button className="task-heading" aria-expanded={open} aria-controls={'task-detail-' + stage.id + task.id} onClick={() => selectTask(open ? '' : task.id)}><span className="task-star">{state === 'completed' ? <Star size={15} fill="currentColor"/> : !unlocked ? <LockKeyhole size={13}/> : <Circle size={13}/>}</span><span><small>行动 {String(i + 1).padStart(2, '0')} · {statusLabel[state]}</small><strong>{task.title}</strong></span><ChevronDown size={14}/></button>
      {open && <div className="task-expanded" id={'task-detail-' + stage.id + task.id}><p>{task.description}</p><dl><dt>你会留下什么</dt><dd>{task.output}</dd><dt>怎样算完成</dt><dd>{task.completion_criteria}</dd></dl><div className="task-meta">{task.effort_hours != null && <span><Clock3 size={12}/>{task.effort_hours} 小时 · 预计</span>}<button className="task-evidence" onClick={() => evidence(task.basis)}>{basisLabel[task.basis.kind]} ↗</button></div><div className="task-skills">{task.skills.map(skill => <span key={skill}>{skill}</span>)}</div>{saved?.note && <p className="task-note">你的记录：{saved.note}</p>}<div className="task-controls"><button className={state === 'completed' ? '' : 'task-complete'} disabled={!allowed || !unlocked} onClick={async () => {await progress(task, state === 'completed' ? 'pending' : 'completed'); selectTask(null)}}>{state === 'completed' ? '重新打开' : <><Star size={13}/>确认完成</>}</button><button disabled={!allowed || state === 'completed'} onClick={() => help(task)}>记录 / 求助</button><button disabled={!allowed} onClick={() => void progress(task, state === 'skipped' ? 'pending' : 'skipped')}>{state === 'skipped' ? '恢复' : '跳过'}</button></div>{!unlocked && <p className="task-locked">先处理前置任务，再点亮这个物件。</p>}</div>}
    </article>
  })}</div>
}

export function GrowthConstellation({work}: {work: PathRun['completed_work']}) {
  const [selected, setSelected] = useState('')
  const skills = Array.from(new Set(work.flatMap(item => item.skills)))
  const points = skills.slice(0, 12).map((skill, i) => ({skill, x: 85 + (i % 4) * 172 + Math.sin(i * 2) * 20, y: 80 + Math.floor(i / 4) * 112 + Math.sin(i * 3) * 25}))
  return <><div className="growth-universe">{points.length > 0 && <svg viewBox="0 0 720 390" preserveAspectRatio="none" aria-hidden="true"><polyline points={points.map(p => `${p.x},${p.y}`).join(' ')} fill="none" stroke="#a9cfcb" strokeOpacity=".25" strokeWidth="1" strokeDasharray="4 5"/></svg>}{points.map(point => <button key={point.skill} className={'growth-star' + (selected === point.skill ? ' selected' : '')} style={{left: point.x / 7.2 + '%', top: point.y / 3.9 + '%'}} onClick={() => setSelected(selected === point.skill ? '' : point.skill)}><Star size={19} fill="currentColor"/>{point.skill}</button>)}{!skills.length && <div className="growth-empty"><Star size={34}/><p>你的第一颗星，正等待一次行动。</p><small>完成任务后，相关能力标签会在这里亮起。</small></div>}</div>{skills.length > 12 && <p className="space-muted">其余成长标签：{skills.slice(12).join(' · ')}</p>}<div className="growth-work-list">{work.filter(item => !selected || item.skills.includes(selected)).map(item => <article key={item.id}><Check size={15}/><div><strong>{item.title}</strong><p>{item.note || '你已报告完成这次行动。'}</p></div></article>)}</div></>
}
