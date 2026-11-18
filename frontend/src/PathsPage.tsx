import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, Check, ChevronRight, Compass, Flag, History, LoaderCircle, Pause, Play, Rocket, Sparkles, Star, X } from 'lucide-react'
import { pathApi } from './pathApi'
import { planetImage } from './pathGraphics'
import type { Basis, PathEvent, PathRun, PathTask, Plan, Stage } from './pathTypes'
import './paths.css'

const basisLabel = {case: '案例证据', synthesis: '综合建议', hypothesis: '待验证假设'}
const statusLabel: Record<string, string> = {pending: '待开始', in_progress: '进行中', blocked: '遇到困难', completed: '已完成', skipped: '已跳过'}

export function PathEntry({ runId }: {runId: string}) {
  const result = useQuery({queryKey: ['path-entry', runId], queryFn: () => pathApi.lookup(runId)})
  return <section className="path-entry"><div><span>下一步 · 把线索变成行动</span><h2>你的下一站，会在哪里？</h2><p>结合这些经历，探索几条适合自己的路线。每一步都可以调整。</p></div>
    <Link to={'/explore/' + runId}><Rocket size={18}/>{result.data?.plan ? '继续太空探索' : '探索我的人生路径'}<ArrowRight size={17}/></Link></section>
}

function Dialog({title, close, children}: {title: string; close: () => void; children: React.ReactNode}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current!
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialog.showModal()
    return () => {dialog.close(); document.body.style.overflow = overflow}
  }, [])
  return <dialog aria-label={title} className="space-dialog" ref={ref} onCancel={close} onClick={e => {if (e.target === e.currentTarget) close()}}><header><h2>{title}</h2><button autoFocus aria-label="关闭" onClick={close}><X size={20}/></button></header><div className="space-dialog-body">{children}</div></dialog>
}

export default function PathsPage() {
  const {runId = ''} = useParams()
  const cache = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [selectedStage, setSelectedStage] = useState('')
  const [panel, setPanel] = useState('')
  const [basis, setBasis] = useState<Basis | null>(null)
  const [custom, setCustom] = useState('')
  const [revision, setRevision] = useState('')
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [events, setEvents] = useState<PathEvent[]>([])
  const [connected, setConnected] = useState(false)
  const [historical, setHistorical] = useState<Plan | null>(null)
  const [flight, setFlight] = useState(false)
  const [taskHelp, setTaskHelp] = useState<PathTask | null>(null)
  const [note, setNote] = useState('')
  const creating = useRef(false)
  useEffect(() => { const previous = document.title; document.title = '人生实验室 · 太空探索'; return () => {document.title = previous} }, [])
  const query = useQuery({queryKey: ['path', runId], queryFn: () => pathApi.lookup(runId), refetchInterval: q => q.state.data?.status === 'running' ? 1500 : 7000})
  const run = query.data
  const save = (value: PathRun) => { cache.setQueryData(['path', runId], value); cache.invalidateQueries({queryKey: ['path-entry', runId]}) }
  useEffect(() => {
    if (query.isSuccess && query.data === null && !creating.current) {
      creating.current = true
      pathApi.create(runId).then(save).catch(e => setError(e.message))
    }
  }, [query.isSuccess, query.data, runId]) // creation is idempotent on the server
  useEffect(() => {
    if (!run?.id) return
    const source = new EventSource(`/api/paths/${run.id}/events`)
    source.onopen = () => setConnected(true)
    source.onerror = () => setConnected(false)
    source.addEventListener('trace', message => {
      const event = JSON.parse((message as MessageEvent).data) as PathEvent
      setEvents(old => old.some(item => item.sequence === event.sequence) ? old : [...old, event].slice(-400))
      cache.invalidateQueries({queryKey: ['path', runId]})
    })
    return () => source.close()
  }, [run?.id, runId, cache])
  const currentId = run?.current_stage_id
  useEffect(() => {if (currentId) {setSelectedStage(currentId); setFlight(false)}}, [currentId])
  async function action(name: string, body: object = {}, method = 'POST') {
    if (!run || busy) return
    setBusy(true); setError('')
    try {save(await pathApi.action(run.id, name, body, method))} catch(e) {setError((e as Error).message); cache.invalidateQueries({queryKey: ['path', runId]}); setFlight(false)} finally {setBusy(false)}
  }
  const input = run?.input_request
  const respond = (body: object) => action('respond', {input_id: input?.id, ...body})
  const plan = run?.plan
  useEffect(() => { if (plan) window.scrollTo({top: 0}) }, [!!plan])
  const stage = plan?.stages.find(s => s.id === selectedStage) || plan?.stages.find(s => s.id === currentId)
  const working = busy || run?.status === 'running'
  const editable = run?.status === 'ready' && run.journey_status === 'active' && !busy
  const done = (s: Stage) => s.already_completed || !!s.tasks.length && s.tasks.every(t => ['completed', 'skipped'].includes(run?.progress[s.id + ':' + t.id]?.status || 'pending'))
  const completed = plan?.stages.filter(done).length || 0
  const choose = (candidate_id?: string) => {
    const body = {candidate_id, custom_goal: candidate_id ? '' : custom}
    if (input?.kind === 'selection') void respond(body)
    else void action('select', {...body, version: run?.version})
    setPanel('')
  }
  const progress = (task: PathTask, status: string, text?: string) => action('progress', {version: run?.version, stage_id: stage?.id, task_id: task.id, status, note: text ?? run?.progress[stage!.id + ':' + task.id]?.note ?? ''}, 'PATCH')
  const candidates = <><p className="space-muted">没有唯一正确的路线。先选一条低成本验证，之后随时调整。</p><div className="route-cards">{run?.candidates.map((candidate, index) => <article key={candidate.id} className="route-card">
    <div className="route-planet"><img src={planetImage(index + 1)} alt=""/><span>航线 0{index + 1}</span></div><h2>{candidate.title}</h2><p>{candidate.goal}</p><button className="basis-chip" onClick={() => setBasis(candidate.basis)}>{basisLabel[candidate.basis.kind]} ↗</button><p>{candidate.approach}</p>
    <dl><dt>适合的条件</dt><dd>{candidate.suitable_conditions.join('；')}</dd><dt>投入与难点</dt><dd>{candidate.effort} · {candidate.difficulties.join('；')}</dd><dt>第一小步</dt><dd>{candidate.first_action}</dd></dl><button className="space-primary" disabled={working} onClick={() => choose(candidate.id)}>选择这条航线<ArrowRight size={16}/></button></article>)}</div>
    <form className="space-custom" onSubmit={e => {e.preventDefault(); choose()}}><label htmlFor="custom-goal">也可以定义自己的方向</label><div><input id="custom-goal" placeholder="例如：保留当前工作，每周用 5 小时验证一个新方向" value={custom} maxLength={1500} onChange={e => setCustom(e.target.value)}/><button disabled={working || custom.trim().length < 5}>按这个方向规划<ChevronRight size={16}/></button></div></form></>

  return <div className="path-page">
    <div className="space-grain"/><header className="space-nav"><Link className="space-brand" to={'/retrieval/' + runId}><span className="space-logo"><Compass size={23}/></span><span>人生实验室<small>LIFELAB / EXPLORER</small></span></Link><nav><button className={panel !== 'skills' ? 'active' : ''} onClick={() => setPanel('')}>我的星图</button><button onClick={() => setPanel('skills')}>成长星座</button><button onClick={() => setPanel('versions')}><History size={15}/>航行记录</button></nav><Link className="space-back" to={'/retrieval/' + runId}><ArrowLeft size={15}/>返回检索</Link></header>
    <div className="space-status"><span><span className={'space-dot' + (working ? ' pulse' : '')}/>{working ? '领航员正在规划' : run?.journey_status === 'paused' ? '已暂停，按自己的节奏来' : run?.journey_status === 'completed' ? '这段探索已完成' : '你的旅程，由你掌舵'}</span><button onClick={() => setPanel('trace')}>{connected ? '●' : '○'} Agent Trace {run?.operation && `· ${run.operation.tokens_used.toLocaleString()} tokens`}</button></div>
    {(error || query.error || run?.error) && <div className="space-error" role="alert">{error || query.error?.message || run?.error}<button disabled={busy} onClick={() => {if (run?.error) void action('retry'); else {creating.current = false; setError(''); void query.refetch()}}}>重试</button></div>}
    {!run && <main className="space-loading"><LoaderCircle className="spin" size={30}/><h1>准备你的星图</h1><p>正在连接已保存的检索结果…</p></main>}
    {run && !plan && input?.kind !== 'selection' && input?.kind !== 'clarification' && <main className="space-loading"><img src={planetImage(2)} alt=""/><span className="space-eyebrow">CHARTING YOUR POSSIBILITIES</span><h1>{run.status === 'failed' ? '这次规划暂未完成' : '每一种可能，都值得被看见。'}</h1><p>正在结合你的背景与检索证据，寻找不同的出发方向。</p>{working && <LoaderCircle className="spin"/>}</main>}
    {run && !plan && input?.kind === 'selection' && <main className="route-selection"><span className="space-eyebrow">A UNIVERSE OF POSSIBILITIES</span><h1>从这里，选择你的下一种可能。</h1>{candidates}</main>}
    {input?.kind === 'clarification' && <main className="space-clarify"><Sparkles/><h1>出发前，再了解你一点。</h1><p>只补充会影响路线选择的信息；暂时不确定也可以直接说明。</p><form onSubmit={e => {e.preventDefault(); void respond({answers})}}>{input.data.questions?.map(q => <label key={q.id}>{q.question}<small>{q.reason}</small><textarea required maxLength={2000} value={answers[q.id] || ''} onChange={e => setAnswers({...answers, [q.id]: e.target.value})}/></label>)}<button className="space-primary" disabled={working}>保存并继续<ArrowRight size={16}/></button></form></main>}
    {plan && stage && <>
      <section className="space-heading"><div><span className="space-eyebrow">YOUR PERSONAL EXPEDITION · V{run.version}</span><h1>{plan.title}</h1><p>{plan.goal}</p></div><div className="space-heading-actions"><button disabled={working} onClick={() => setPanel('routes')}>切换航线</button><button disabled={working} onClick={() => setPanel('revise')}>调整计划</button><button aria-label={run.journey_status === 'paused' ? '继续探索' : '暂停探索'} disabled={working} onClick={() => void action('journey', {paused: run.journey_status !== 'paused'}, 'PATCH')}>{run.journey_status === 'paused' ? <Play size={15}/> : <Pause size={15}/>}</button></div></section>
      <div className="expedition-layout"><main className="space-map-column"><div className="map-caption"><span><Compass size={15}/>你的成长航线</span><small>{completed} / {plan.stages.length} 颗星球已探索</small></div>
        <div className={'space-map' + (flight ? ' flying' : '')} aria-label="阶段星图"><svg className="space-orbits" viewBox="0 0 1000 560" preserveAspectRatio="none"><defs><linearGradient id="orbit-color"><stop stopColor="#70b3a9"/><stop offset="1" stopColor="#767099"/></linearGradient></defs><path d={plan.stages.map((_, i) => {const x = 105 + i * 790 / (plan.stages.length - 1), y = i % 2 ? 325 : 190; return `${i ? 'L' : 'M'} ${x} ${y}`}).join(' ')} fill="none" stroke="url(#orbit-color)" strokeWidth="1.3" strokeDasharray="4 8"/></svg>
          {plan.stages.map((s, i) => <button key={s.id} className={'map-planet' + (s.id === stage.id ? ' selected' : '') + (done(s) ? ' explored' : '')} style={{left: `${10.5 + i * 79 / (plan.stages.length - 1)}%`, top: `${i % 2 ? 58 : 34}%`}} onClick={() => {setSelectedStage(s.id); if (window.innerWidth < 900) document.getElementById('mission-pane')?.scrollIntoView({behavior: 'smooth'})}}><span className="planet-orbit"/><img src={planetImage(i)} alt=""/><span className="planet-number">{done(s) ? <Check size={12}/> : String(i + 1).padStart(2, '0')}</span><strong>{s.title}</strong><small>{s.id === currentId ? '当前停靠' : done(s) ? '已探索' : '等待探索'}</small></button>)}
          <span className="space-ship" aria-label="当前位置" style={{left: `${10.5 + Math.max(0, plan.stages.findIndex(s => s.id === currentId)) * 79 / (plan.stages.length - 1)}%`, top: `${Math.max(0, plan.stages.findIndex(s => s.id === currentId)) % 2 ? 58 : 34}%`}}><Rocket size={26}/></span><div className="map-footnote"><Star size={13}/>每一次小小的行动，都在让你的宇宙变亮。</div></div>
        <div className="journey-strip"><span className="strip-icon"><Rocket size={23}/></span><div><small>当前坐标</small><strong>{plan.stages.find(s => s.id === currentId)?.title}</strong></div><div className="journey-progress"><div style={{width: `${completed / plan.stages.length * 100}%`}}/></div><span>{Math.round(completed / plan.stages.length * 100)}%</span></div>
        <details className="space-limitations"><summary>规划依据与边界 · {plan.limitations.length} 条提醒</summary>{plan.limitations.map((text, i) => <p key={i}>{text}</p>)}<p>任务完成由你自行报告；预计投入不代表结果保证。</p></details>
      </main><aside className="mission-pane" id="mission-pane"><div className="mission-top"><span className="space-eyebrow">MISSION / {String(plan.stages.indexOf(stage) + 1).padStart(2, '0')}</span><button className="mobile-map-back" onClick={() => window.scrollTo({top: 0, behavior: 'smooth'})}>返回星图 ↑</button><span className="mission-state">{stage.id === currentId ? '当前阶段' : '阶段预览'}</span></div><div className="mission-body"><h2>{stage.title}</h2><p>{stage.objective}</p><button className="basis-chip" onClick={() => setBasis(stage.basis)}>{basisLabel[stage.basis.kind]} ↗</button><div className="stage-criteria"><Flag size={15}/><div><strong>抵达的标志</strong><p>{stage.completion_criteria}</p>{stage.effort_hours_min != null && <small>预计投入 {stage.effort_hours_min}–{stage.effort_hours_max ?? stage.effort_hours_min} 小时</small>}</div></div>
        <div className="task-section-title"><h3>这一站的小行动</h3><span>{stage.tasks.length} 个任务</span></div>
        {!stage.tasks.length && <div className="unexpanded"><p>后续阶段先保留方向，抵达时再展开具体任务。</p><button disabled={working} onClick={() => void action('expand', {stage_id: stage.id, version: run.version})}>提前展开这一站</button></div>}
        {stage.tasks.map((task, i) => {const saved = run.progress[stage.id + ':' + task.id]; const state = saved?.status || 'pending'; const unlocked = task.depends_on.every(id => ['completed', 'skipped'].includes(run.progress[stage.id + ':' + id]?.status || 'pending')); const allowed = editable && plan.stages.indexOf(stage) <= plan.stages.findIndex(s => s.id === currentId); return <article className={'space-task task-' + state} key={task.id}><div className="task-title"><span>{state === 'completed' ? <Star size={16} fill="currentColor"/> : `0${i + 1}`}</span><h4>{task.title}</h4><small>{statusLabel[state]}</small></div><p>{task.description}</p><dl><dt>产出</dt><dd>{task.output}</dd><dt>完成标准</dt><dd>{task.completion_criteria}</dd></dl>{task.effort_hours != null && <small>预计 {task.effort_hours} 小时</small>}<div className="task-skills">{task.skills.map(skill => <span key={skill}>{skill}</span>)}</div><button className="task-evidence" onClick={() => setBasis(task.basis)}>{basisLabel[task.basis.kind]} ↗</button>{saved?.note && <p className="task-note">你的记录：{saved.note}</p>}<div className="task-controls"><button disabled={!allowed || !unlocked} onClick={() => void progress(task, state === 'completed' ? 'pending' : 'completed')}>{state === 'completed' ? '重新打开' : <><Check size={13}/>点亮这颗星</>}</button><button disabled={!allowed || state === 'completed'} onClick={() => {setTaskHelp(task); setNote(saved?.note || '')}}>记录 / 求助</button><button disabled={!allowed} onClick={() => void progress(task, state === 'skipped' ? 'pending' : 'skipped')}>{state === 'skipped' ? '恢复' : '跳过'}</button></div>{!unlocked && state !== 'completed' && <small>请先处理前置任务</small>}</article>})}</div>
        <div className="mission-actions"><button className="space-primary" disabled={!editable || stage.id !== currentId || !done(stage)} onClick={() => {setFlight(true); void action('advance', {stage_id: stage.id, version: run.version})}}>{working ? <LoaderCircle size={17} className="spin"/> : <Rocket size={17}/>} {run.journey_status === 'completed' ? '探索已完成' : plan.stages.indexOf(stage) === plan.stages.length - 1 ? '完成这段探索' : '启程，前往下一站'}<ArrowRight size={17}/></button><small>不必赶路，按自己的节奏前进。</small></div></aside></div></>}
    {input?.kind === 'revision' && run?.pending_revision && <Dialog title="确认这次航线调整" close={() => {void respond({approve: false})}}><p>原计划：{plan?.title}</p><h3>{run.pending_revision.title}</h3>{run.pending_revision.stages.map(s => <div className="revision-stage" key={s.id}><strong>{s.title}</strong><p>{s.objective}</p></div>)}<p>已完成的行动记录会保留，只有确认后才保存新版本。</p><div className="dialog-actions"><button disabled={working} onClick={() => void respond({approve: false})}>保留原计划</button><button className="space-primary" disabled={working} onClick={() => void respond({approve: true})}>采用新计划</button></div></Dialog>}
    {panel && <Dialog title={({routes: '选择另一条航线', revise: '调整你的探索计划', trace: '路径 Agent · 运行轨迹', versions: '航行记录与计划版本', skills: '你的成长星座'} as Record<string, string>)[panel]} close={() => {setPanel(''); setHistorical(null)}}>
      {panel === 'routes' && candidates}
      {panel === 'revise' && <form onSubmit={e => {e.preventDefault(); void action('revise', {version: run?.version, instruction: revision}); setPanel('')}}><p>说说你的新情况，例如每周时间减少、目标变化、已有能力或遇到困难。新计划需要你确认后才生效。</p><textarea required minLength={5} maxLength={3000} value={revision} onChange={e => setRevision(e.target.value)} placeholder="我每周只能投入 4 小时，希望降低强度，先验证方向…"/><button className="space-primary" disabled={working || revision.trim().length < 5}>生成调整方案</button></form>}
      {panel === 'trace' && <><p className="space-muted">展示工作流节点、证据校验和预算使用，不展示模型内部思考。{connected ? '实时连接中' : '连接恢复中，页面仍会轮询更新'}</p>{run?.operation && <p>本次操作：{run.operation.kind} · {run.operation.tokens_used} / {run.operation.limits.tokens} tokens · {Math.round(run.operation.elapsed_seconds)} / {run.operation.limits.seconds} 秒</p>}<ol className="path-events">{events.map(event => <li key={event.sequence}><small>{new Date(event.occurred_at * 1000).toLocaleTimeString()} · {event.node}</small><strong>{event.title}</strong><details><summary>节点数据</summary><pre>{JSON.stringify(event.payload, null, 2)}</pre></details></li>)}</ol></>}
      {panel === 'versions' && <><p>所有进度保存在本地。旧版本只读，切换方向不会抹去已经完成的行动。</p>{run?.versions.slice().reverse().map(v => <button className="version-row" key={v.version} onClick={() => {pathApi.version(run.id, v.version).then(setHistorical).catch(e => setError(e.message))}}><span>V{v.version} · {v.title}<small>{v.reason}</small></span><ChevronRight size={16}/></button>)}{historical && <section><h3>V{historical.version} · {historical.title}</h3>{historical.stages.map(s => <p key={s.id}>{s.title} — {s.objective}</p>)}</section>}</>}
      {panel === 'skills' && <><p>星座来自你已报告完成的任务，不代表经过外部认证的能力。</p><div className="skill-constellation">{Array.from(new Set(run?.completed_work.flatMap(t => t.skills))).map((skill, i) => <span key={skill} style={{transform: `translateY(${i % 2 * 24}px)`}}><Star size={20} fill="currentColor"/>{skill}</span>)}</div>{!run?.completed_work.length && <p className="space-muted">完成第一个行动，让你的第一颗成长之星亮起来。</p>}{run?.completed_work.map(t => <div className="revision-stage" key={t.id}><strong>✦ {t.title}</strong>{t.note && <p>{t.note}</p>}</div>)}</>}
    </Dialog>}
    {basis && <Dialog title={basisLabel[basis.kind]} close={() => setBasis(null)}><p>{basis.explanation}</p>{basis.validation_action && <p className="stage-criteria">验证方法：{basis.validation_action}</p>}{basis.evidence_ids.map(id => {const evidence = run?.evidence_catalog[id]; return evidence && <blockquote key={id}><p>“{evidence.quote}”</p><small>{evidence.value}</small>{evidence.source.url && /^https?:\/\//.test(evidence.source.url) && <a href={evidence.source.url} target="_blank" rel="noreferrer">{evidence.source.title || '查看知乎来源'} ↗</a>}</blockquote>})}{!basis.evidence_ids.length && <p className="space-muted">这条建议没有直接案例引文，需要结合你的实际情况验证。</p>}</Dialog>}
    {taskHelp && <Dialog title="记录这一步的进展与困难" close={() => setTaskHelp(null)}><h3>{taskHelp.title}</h3><p>可以先试试：{taskHelp.help_hint}</p><label>你的进展、产出或遇到的困难<textarea value={note} maxLength={2000} onChange={e => setNote(e.target.value)} placeholder="记录实际发生的事，之后调整计划时会保留这些信息。"/></label><div className="dialog-actions"><button disabled={!editable} onClick={() => {void progress(taskHelp, 'blocked', note); setTaskHelp(null)}}>记录困难</button><button className="space-primary" disabled={!editable} onClick={() => {void progress(taskHelp, 'in_progress', note); setTaskHelp(null)}}>保存进展</button></div><small className="space-muted">情感陪伴 Agent 尚未接入；这里提供任务建议与记录。</small></Dialog>}
  </div>
}
