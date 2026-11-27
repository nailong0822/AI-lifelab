import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, ChevronRight, Compass, Flag, History, LoaderCircle, Pause, Play, Rocket, Sparkles, Star, X, MessageCircle } from 'lucide-react'
import { pathApi } from './pathApi'
import { planetImage } from './pathGraphics'
import type { Basis, PathEvent, PathRun, PathTask, Plan, Stage } from './pathTypes'
import { ThemeToggle } from './ThemeProvider'
import { GrowthConstellation, MissionTasks } from './components/JourneyUI'
import { RoutePlanner } from './components/RoutePlanner'
import { JourneyViewport, StageRail } from './components/JourneyViewport'
import { useJourneyRewards } from './useJourneyRewards'
import { useJourneyTransfer } from './useJourneyTransfer'
import { TransferJourney } from './components/TransferJourney'
import { useCompanion } from './components/CompanionDock'
import { ExperiencePanel } from './components/ExperiencePanel'
import { AccountControls } from './AuthProvider'
import './paths.css'
import './flight.css'

const basisLabel = {case: '案例证据', synthesis: '综合建议', hypothesis: '待验证假设'}

export function PathEntry({ runId }: {runId: string}) {
  const result = useQuery({queryKey: ['path-entry', runId], queryFn: () => pathApi.lookup(runId)})
  return <section className="path-entry"><div className="path-entry-art" aria-hidden="true"><span/><img src={planetImage(4)} alt=""/></div><div><span>下一步 · 把线索变成行动</span><h2>你的下一站，会在哪里？</h2><p>结合这些经历，探索几条适合自己的路线。每一步都可以调整。</p></div>
    <Link to={'/explore/' + runId}><Rocket size={18}/>{result.data?.plan ? '继续太空探索' : '探索我的人生路径'}<ArrowRight size={17}/></Link></section>
}

export function Dialog({title, close, children}: {title: string; close: () => void; children: React.ReactNode}) {
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
  const [focusedTask, setFocusedTask] = useState<{stageId: string; taskId: string} | null>(null)
  const [panel, setPanel] = useState('')
  const [basis, setBasis] = useState<Basis | null>(null)
  const [custom, setCustom] = useState('')
  const [revision, setRevision] = useState('')
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [events, setEvents] = useState<PathEvent[]>([])
  const [connected, setConnected] = useState(false)
  const [historical, setHistorical] = useState<Plan | null>(null)
  const [toast, setToast] = useState('')
  useEffect(() => {if (!toast) return; const timer = setTimeout(() => setToast(''), 3500); return () => clearTimeout(timer)}, [toast])
  const {openCompanion,isOpen:companionOpen} = useCompanion()
  const [experienceOpen,setExperienceOpen]=useState(false)
  const creating = useRef(false)
  useEffect(() => { const previous = document.title; document.title = '人生实验室 · 太空探索'; return () => {document.title = previous} }, [])
  const query = useQuery({queryKey: ['path', runId], queryFn: () => pathApi.lookup(runId), refetchInterval: q => q.state.data?.status === 'running' ? 1500 : 7000})
  const run = query.data
  const rewards = useJourneyRewards(run)
  const {transfer,finish:finishTransfer}=useJourneyTransfer(run)
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
  useEffect(() => {if (currentId) {setSelectedStage(currentId)}}, [currentId])
  async function action(name: string, body: object = {}, method = 'POST') {
    if (!run || busy || transfer) return
    setBusy(true); setError('')
    try {
      const updated = await pathApi.action(run.id, name, body, method)
      save(updated)
      if (name === 'advance') setToast(updated.journey_status === 'completed' ? '这段旅程已完成。新的可能，正等着你。' : '坐标已更新，正在准备下一站。')
    } catch(e) {setError((e as Error).message); cache.invalidateQueries({queryKey: ['path', runId]})} finally {setBusy(false)}
  }
  const input = run?.input_request
  const respond = (body: object) => action('respond', {input_id: input?.id, ...body})
  const plan = run?.plan
  const missionRef = useRef<HTMLElement>(null)
  useEffect(() => { if (plan) window.scrollTo({top: 0}) }, [!!plan])
  const stage = plan?.stages.find(s => s.id === selectedStage) || plan?.stages.find(s => s.id === currentId)
  useEffect(() => {missionRef.current?.querySelector('.mission-body')?.scrollTo({top:0})}, [stage?.id])
  const inspectStage = (next: Stage) => {
    setSelectedStage(next.id); setFocusedTask(null)
    requestAnimationFrame(() => document.querySelector('.planet-orbit-scene')?.scrollIntoView({block:'start', behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'}))
  }
  const selectedTaskId = focusedTask && stage && focusedTask.stageId === stage.id && (focusedTask.taskId === '' || stage.tasks.some(t => t.id === focusedTask.taskId))
    ? focusedTask.taskId : stage?.tasks.find(t => !['completed', 'skipped'].includes(run?.progress[stage.id + ':' + t.id]?.status || 'pending'))?.id || ''
  const selectTask = (taskId: string | null) => setFocusedTask(taskId === null || !stage ? null : {stageId: stage.id, taskId})
  const inspectTask = (taskId: string) => {
    selectTask(taskId)
    requestAnimationFrame(() => {
      const target = document.getElementById('task-detail-' + stage?.id + taskId)
      target?.scrollIntoView({block: 'nearest', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'})
    })
  }
  const working = busy || run?.status === 'running' || !!transfer
  const editable = run?.status === 'ready' && run.journey_status === 'active' && !busy && !transfer
  const done = (s: Stage) => s.already_completed || !!s.tasks.length && s.tasks.every(t => ['completed', 'skipped'].includes(run?.progress[s.id + ':' + t.id]?.status || 'pending'))
  const completed = plan?.stages.filter(done).length || 0
  const choose = (candidate_id?: string) => {
    const body = {candidate_id, custom_goal: candidate_id ? '' : custom}
    if (input?.kind === 'selection') void respond(body)
    else void action('select', {...body, version: run?.version})
    setPanel('')
  }
  const progress = (task: PathTask, status: string, text?: string) => action('progress', {version: run?.version, stage_id: stage?.id, task_id: task.id, status, note: text ?? run?.progress[stage!.id + ':' + task.id]?.note ?? ''}, 'PATCH')
  const candidates = <>

    <RoutePlanner candidates={run?.candidates||[]} busy={!!working} choose={choose} evidence={setBasis} onChat={()=>{setPanel('');openCompanion(run ? {path:run}:undefined)}}/>
    <form className="space-custom" onSubmit={e => {e.preventDefault(); choose()}}><label htmlFor="custom-goal"><Compass size={18}/><span>有自己的方向？</span></label><div><input id="custom-goal" placeholder="写下你的目标、可投入的时间与需要保留的条件" value={custom} maxLength={1500} onChange={e => setCustom(e.target.value)}/><button disabled={working || custom.trim().length < 5}>按这个方向规划<ChevronRight size={16}/></button></div></form>
  </>

  return <div className={'path-page flight-page'+(companionOpen?' with-companion':'')+(transfer?' is-transferring':'')}>
    <header className="space-nav"><Link className="space-brand" to={'/retrieval/' + runId}><span className="space-logo"><Compass size={23}/></span><span>人生实验室</span></Link><nav><button className={!['skills','versions'].includes(panel) ? 'active' : ''} onClick={() => setPanel('')}>我的星图</button><button className={panel === 'skills' ? 'active' : ''} onClick={() => setPanel('skills')}>成长星座</button>{plan && <button onClick={() => {openCompanion({path: run})}}><MessageCircle size={15}/>随航伙伴</button>}<button className={panel === 'versions' ? 'active' : ''} onClick={() => setPanel('versions')}><History size={15}/>航行记录</button></nav><div className="space-nav-actions"><ThemeToggle/><AccountControls/><Link className="space-back" to={'/retrieval/' + runId}><ArrowLeft size={15}/>返回检索</Link></div></header>
    <div className="space-status"><span><span className={'space-dot' + (working ? ' pulse' : '')}/>{working ? '领航员正在规划' : run?.journey_status === 'paused' ? '已暂停，按自己的节奏来' : run?.journey_status === 'completed' ? '这段探索已完成' : run?.journey_status==='ended'?'这段探索已结束':'你的旅程，由你掌舵'}</span><button onClick={() => setPanel('trace')}>{connected ? '●' : '○'} Agent Trace {run?.operation && `· ${run.operation.tokens_used.toLocaleString()} tokens`}</button></div>
    {(error || query.error || run?.error) && <div className="space-error" role="alert">{error || query.error?.message || run?.error}<button disabled={busy} onClick={() => {if (run?.error) void action('retry'); else {creating.current = false; setError(''); void query.refetch()}}}>重试</button></div>}
    {!run && <main className="space-loading"><LoaderCircle className="spin" size={30}/><h1>准备你的星图</h1><p>正在连接已保存的检索结果…</p></main>}
    {run && !plan && input?.kind !== 'selection' && input?.kind !== 'clarification' && <main className="space-loading"><img src={planetImage(2)} alt=""/><h1>{run.status === 'failed' ? '这次规划暂未完成' : '正在规划路径'}</h1><p>正在结合你的背景与检索证据，寻找不同的出发方向。</p>{working && <LoaderCircle className="spin"/>}</main>}
    {run && !plan && input?.kind === 'selection' && <main className="route-selection"><h1>选择探索方向</h1>{candidates}</main>}
    {input?.kind === 'clarification' && <main className="space-clarify"><Sparkles/><h1>出发前，再了解你一点。</h1><p>只补充会影响路线选择的信息；暂时不确定也可以直接说明。</p><form onSubmit={e => {e.preventDefault(); void respond({answers})}}>{input.data.questions?.map(q => <label key={q.id}>{q.question}<small>{q.reason}</small><textarea required maxLength={2000} value={answers[q.id] || ''} onChange={e => setAnswers({...answers, [q.id]: e.target.value})}/></label>)}<button className="space-primary" disabled={working}>保存并继续<ArrowRight size={16}/></button></form></main>}
    {plan && stage && <>
      <section className="space-heading"><div><span className="space-eyebrow">计划 V{run.version}</span><h1>{plan.title}</h1><p>{plan.goal}</p></div><div className="space-heading-actions"><button disabled={working} onClick={()=>setExperienceOpen(true)}>经历复盘</button><button disabled={working} onClick={() => setPanel('routes')}>切换航线</button><button disabled={working} onClick={() => setPanel('revise')}>调整计划</button><button aria-label={run.journey_status === 'paused' ? '继续探索' : '暂停探索'} disabled={working || ['completed','ended'].includes(run.journey_status)} onClick={() => void action('journey', {paused: run.journey_status !== 'paused'}, 'PATCH')}>{run.journey_status === 'paused' ? <Play size={15}/> : <Pause size={15}/>}</button></div></section>
      <StageRail stages={plan.stages} currentId={currentId||null} selectedId={stage.id} done={done} select={inspectStage}/>
      <div className="expedition-layout"><main className="space-map-column"><div className="map-caption"><span><Compass size={15}/>你的成长航线</span><small>{completed} / {plan.stages.length} 颗星球已探索</small></div>
        <JourneyViewport stage={stage} index={plan.stages.indexOf(stage)} progress={run.progress} selectedTaskId={selectedTaskId} selectTask={inspectTask} onChat={()=>openCompanion({path:run,stageId:stage.id})} {...rewards}/>
        <details className="space-limitations"><summary>规划依据与边界 · {plan.limitations.length} 条提醒</summary>{plan.limitations.map((text, i) => <p key={i}>{text}</p>)}<p>任务完成由你自行报告；预计投入不代表结果保证。</p></details>
      </main><aside ref={missionRef} className="mission-pane" id="mission-pane"><div className="mission-top"><span className="space-eyebrow">行动面板 · {String(plan.stages.indexOf(stage) + 1).padStart(2, '0')}</span><button className="mobile-map-back" onClick={() => window.scrollTo({top: 0, behavior: 'smooth'})}>返回星图 ↑</button><span className="mission-state">{stage.id === currentId ? '当前阶段' : '阶段预览'}</span></div><div className="mission-body"><h2>{stage.title}</h2><p>{stage.objective}</p><button className="basis-chip" onClick={() => setBasis(stage.basis)}>{basisLabel[stage.basis.kind]} ↗</button><div className="stage-criteria"><Flag size={15}/><div><strong>抵达的标志</strong><p>{stage.completion_criteria}</p>{stage.effort_hours_min != null && <small>预计投入 {stage.effort_hours_min}–{stage.effort_hours_max ?? stage.effort_hours_min} 小时</small>}</div></div>
        <div className="task-section-title"><h3>这一站的小行动</h3><span>{stage.tasks.length} 个任务</span></div>
        {!stage.tasks.length && <div className="unexpanded"><p>后续阶段先保留方向，抵达时再展开具体任务。</p><button disabled={working} onClick={() => void action('expand', {stage_id: stage.id, version: run.version})}>提前展开这一站</button></div>}
        <MissionTasks selectedTaskId={selectedTaskId} selectTask={selectTask} stage={stage} run={run} editable={!!editable} progress={progress} evidence={setBasis} help={task => {openCompanion({path: run, task, stageId: stage.id})}}/></div>
        <div className="mission-actions"><button className="space-primary" disabled={!editable || stage.id !== currentId || !done(stage) || rewards.rewards.length>0} onClick={() => {void action('advance', {stage_id: stage.id, version: run.version})}}>{working ? <LoaderCircle size={17} className="spin"/> : <Rocket size={17}/>} {run.journey_status === 'completed' ? '探索已完成' : done(stage)&&rewards.rewards.length>0 ? '奶龙正在收集行动之星' : plan.stages.indexOf(stage) === plan.stages.length - 1 ? '完成这段探索' : '登舱，前往下一站'}<ArrowRight size={17}/></button></div></aside></div></>}
    {input?.kind === 'revision' && run?.pending_revision && <Dialog title="确认这次航线调整" close={() => {void respond({approve: false})}}><p>原计划：{plan?.title}</p><h3>{run.pending_revision.title}</h3>{run.pending_revision.stages.map(s => <div className="revision-stage" key={s.id}><strong>{s.title}</strong><p>{s.objective}</p></div>)}<p>已完成的行动记录会保留，只有确认后才保存新版本。</p><div className="dialog-actions"><button disabled={working} onClick={() => void respond({approve: false})}>保留原计划</button><button className="space-primary" disabled={working} onClick={() => void respond({approve: true})}>采用新计划</button></div></Dialog>}
    {panel && <Dialog title={({routes: '选择另一条航线', revise: '调整你的探索计划', trace: '路径 Agent · 运行轨迹', versions: '航行记录与计划版本', skills: '你的成长星座'} as Record<string, string>)[panel]} close={() => {setPanel(''); setHistorical(null)}}>
      {panel === 'routes' && candidates}
      {panel === 'revise' && <form onSubmit={e => {e.preventDefault(); void action('revise', {version: run?.version, instruction: revision}); setPanel('')}}><p>说说你的新情况，例如每周时间减少、目标变化、已有能力或遇到困难。新计划需要你确认后才生效。</p><textarea required minLength={5} maxLength={3000} value={revision} onChange={e => setRevision(e.target.value)} placeholder="我每周只能投入 4 小时，希望降低强度，先验证方向…"/><button className="space-primary" disabled={working || revision.trim().length < 5}>生成调整方案</button></form>}
      {panel === 'trace' && <><p className="space-muted">展示工作流节点、证据校验和预算使用，不展示模型内部思考。{connected ? '实时连接中' : '连接恢复中，页面仍会轮询更新'}</p>{run?.operation && <p>本次操作：{run.operation.kind} · {run.operation.tokens_used} / {run.operation.limits.tokens} tokens · {Math.round(run.operation.elapsed_seconds)} / {run.operation.limits.seconds} 秒</p>}<ol className="path-events">{events.map(event => <li key={event.sequence}><small>{new Date(event.occurred_at * 1000).toLocaleTimeString()} · {event.node}</small><strong>{event.title}</strong><details><summary>节点数据</summary><pre>{JSON.stringify(event.payload, null, 2)}</pre></details></li>)}</ol></>}
      {panel === 'versions' && <><p>所有进度保存在本地。旧版本只读，切换方向不会抹去已经完成的行动。</p>{run?.versions.slice().reverse().map(v => <button className="version-row" key={v.version} onClick={() => {pathApi.version(run.id, v.version).then(setHistorical).catch(e => setError(e.message))}}><span>V{v.version} · {v.title}<small>{v.reason}</small></span><ChevronRight size={16}/></button>)}{historical && <section><h3>V{historical.version} · {historical.title}</h3>{historical.stages.map(s => <p key={s.id}>{s.title} — {s.objective}</p>)}</section>}</>}
      {panel === 'skills' && <><p className="space-muted">每颗星都来自你已完成的行动。点击一个能力标签，回看它背后的真实记录。</p><GrowthConstellation work={run?.completed_work || []}/><p className="growth-disclaimer">能力标签由任务提取，完成状态来自你的反馈，不代表外部能力认证。</p></>}
    </Dialog>}
    {basis && <Dialog title={basisLabel[basis.kind]} close={() => setBasis(null)}><p>{basis.explanation}</p>{basis.validation_action && <p className="stage-criteria">验证方法：{basis.validation_action}</p>}{basis.evidence_ids.map(id => {const evidence = run?.evidence_catalog[id]; return evidence && <blockquote key={id}><p>“{evidence.quote}”</p><small>{evidence.value}</small>{evidence.source.url && /^(https?:\/\/|\/shared-cases\/)/.test(evidence.source.url) && <a href={evidence.source.url} target="_blank" rel="noreferrer">{evidence.source.title || '查看知乎来源'} ↗</a>}</blockquote>})}{!basis.evidence_ids.length && <p className="space-muted">这条建议没有直接案例引文，需要结合你的实际情况验证。</p>}</Dialog>}
    {run && experienceOpen && <ExperiencePanel path={run} close={()=>setExperienceOpen(false)} refresh={()=>{void cache.invalidateQueries({queryKey:['path',runId]});void cache.invalidateQueries({queryKey:['path-entry',runId]})}}/>}
    {toast && <div className="journey-toast" role="status"><Star size={16} fill="currentColor"/><span>{toast}</span></div>}
    {transfer&&<TransferJourney key={transfer.id} transfer={transfer} finish={finishTransfer}/>}
  </div>
}
