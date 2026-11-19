import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight, ArrowUpRight, BookOpen, Check, CheckCircle2, ChevronDown,
  Circle, CircleAlert, Clock3, ExternalLink, History, LoaderCircle,
  Menu, MessageSquare, Plus, Search, Sparkles, Square, WifiOff, X, Compass, Orbit, Radio, Star as StarIcon,
} from 'lucide-react'
import { api } from './api'
import PathsPage, { Dialog, PathEntry } from './PathsPage'
import SharedCasePage from './SharedCasePage'
import { JourneySteps, ObservatoryScene, Starfield } from './components/Universe'
import { ThemeToggle } from './ThemeProvider'
import { Button } from './components/ui/button'
import type { Case, Health, Run, RunSummary, TraceEvent } from './types'

const statusLabels: Record<string, string> = {
  running: '探索中', awaiting_input: '等待补充', finished: '已完成', failed: '执行受限', cancelled: '已停止',
}
const reasonLabels: Record<string, string> = {
  request_limit: '已达到 4 次检索上限', time_budget: '剩余时间预算不足', token_budget: '剩余 Token 预算不足',
  coverage_met: '关键证据已覆盖', no_new_evidence: '连续检索未获得新证据',
  no_valid_query: '当前缺口暂无有效补查方向', service_error: '服务调用受限', cancelled: '你已停止本次检索',
}
const factLabels: Record<string, string> = {
  person_context: '人物背景', actions: '采取的行动', stage_outcomes: '阶段结果',
  time_and_cost: '时间与成本', event_time: '经历时间',
  major: '专业', education: '学历', year: '年级', career_stage: '职业阶段',
  target: '目标方向', plans: '计划与路径', starting_point: '起点能力', constraints: '现实约束',
}
const coverageLabels: Record<string, string> = {
  clear: '证据明确', partial: '证据不完整', undisclosed: '结果未交代', missing: '尚未找到',
}
const examples = [
  '生物专业研一，想在读期间准备 AI Agent 开发实习',
  '工作两年，想了解跨专业申请研究生的真实经历',
  '想从传统行业转向软件开发，如何低成本验证方向',
]
const terminal = (run: Run) => ['finished', 'failed', 'cancelled'].includes(run.status)
const timeText = (value: number) => new Date(value * 1000).toLocaleTimeString('zh-CN', {
  hour: '2-digit', minute: '2-digit', second: '2-digit',
})

function Status({ status }: { status: string }) {
  return <span className={'status status-' + status}>
    {status === 'running' ? <LoaderCircle className="spin" size={13} /> : <span className="status-dot" />}
    {statusLabels[status] || status}
  </span>
}

function Sidebar({ history, close }: { history: RunSummary[]; close: () => void }) {
  return <aside className="sidebar">
    <Link className="brand" to="/retrieval" onClick={close}>
      <span className="brand-symbol"><Orbit size={25} strokeWidth={1.3} /></span>
      <span><strong>人生实验室</strong><small>LIFELAB · YOUR NEXT ORBIT</small></span>
    </Link>
    <Button asChild className="new-button"><Link to="/retrieval" onClick={close}><Plus size={17} />开启新的探索</Link></Button>
    <nav aria-label="主要导航">
      <NavLink to="/retrieval" className={({ isActive }) => 'nav-item' + (isActive ? ' active' : '')} onClick={close}><Compass size={18} />深空观测站<ArrowUpRight size={15} /></NavLink>
      <NavLink to="/history" className={({ isActive }) => 'nav-item' + (isActive ? ' active' : '')} onClick={close}><History size={18} />探索档案</NavLink>
    </nav>
    <div className="history-label">最近的探索</div>
    <div className="recent-list">
      {history.length ? history.slice(0, 8).map(run =>
        <Link key={run.id} to={'/retrieval/' + run.id} className="recent-item" onClick={close}>
          <MessageSquare size={15} /><span>{run.question}</span>
          {run.status === 'running' && <span className="recent-dot" />}
        </Link>) : <p className="history-empty">你的探索会保存在这里</p>}
    </div>
    <div className="sidebar-manifest"><Orbit size={25}/><p>人生没有标准航线。<br/>每一次探索，都算数。</p><span>STAY CURIOUS. KEEP GOING.</span></div>
    <div className="sidebar-foot"><span className="leaf-dot" />你的探索，保存在本地</div>
  </aside>
}

function Composer({ health, question, setQuestion, onSubmit, pending }: {
  health?: Health; question: string; setQuestion: (text: string) => void; onSubmit: () => void; pending: boolean
}) {
  const configured = health?.model_configured && health.zhihu_configured
  return <form className="composer" onSubmit={event => { event.preventDefault(); onSubmit() }}>
    <div className="composer-caption"><span><Radio size={13}/>向未知，发送你的第一个信号</span><small>01 / YOUR QUESTION</small></div>
    <textarea aria-label="描述你想探索的问题" placeholder="说说你的背景、正在考虑的选择，以及让你犹豫的地方…"
      value={question} onChange={event => setQuestion(event.target.value)} maxLength={6000}
      onKeyDown={event => {
        if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && question.trim().length >= 5 && configured) {
          event.preventDefault(); onSubmit()
        }
      }} />
    <div className="composer-footer">
      <span><BookOpen size={15} />从真实经历出发<span className="composer-shortcut">Ctrl / ⌘ + Enter</span></span>
      <Button type="submit" disabled={pending || !configured || question.trim().length < 5}>
        {pending ? <LoaderCircle size={16} className="spin" /> : <>开始探索<ArrowUpRight size={17} /></>}
      </Button>
    </div>
  </form>
}

function NewRun({ health }: { health?: Health }) {
  const [question, setQuestion] = useState('')
  const navigate = useNavigate()
  const cache = useQueryClient()
  const create = useMutation({
    mutationFn: () => api.create(question),
    onSuccess: run => { cache.invalidateQueries({ queryKey: ['history'] }); navigate('/retrieval/' + run.id) },
  })
  return <div className="observatory-home">
    <JourneySteps active={0}/>
    <div className="observatory-hero">
    <main className="new-workspace">
      <div className="eyebrow"><span />给人生一点，新的可能 <span className="eyebrow-line"/></div>
      <h1>人生没有标准航线。<br /><em>先看见你的可能。</em></h1>
      <p className="intro">有人走过你正犹豫的路。<br/>从他们的真实经历出发，找到属于自己的下一步。</p>
      <Composer health={health} question={question} setQuestion={setQuestion} onSubmit={() => create.mutate()} pending={create.isPending} />
      {create.error && <p className="inline-error" role="alert"><CircleAlert size={16} />{create.error.message}</p>}
      <div className="examples"><span>还没想好？从一个念头开始</span><div className="example-chips">
        {examples.map(example => <button type="button" key={example} onClick={() => setQuestion(example)}>
          <span>{['跨专业，寻找新方向', '升学，看看另一种可能', '转行，先做一次小实验'][examples.indexOf(example)]}</span><ArrowUpRight size={13} />
        </button>)}
      </div></div>
    </main>
    <ObservatoryScene />
    </div>
    <div className="observatory-principles">{[{icon: BookOpen, number: '01', title: '让经历成为坐标', text: '检索知乎分享与授权的匿名经历，每条线索都有来源。'}, {icon: Orbit, number: '02', title: '让选择多一种可能', text: '比较不同方向，用小实验验证适合自己的路。'}, {icon: StarIcon, number: '03', title: '让改变发生在今天', text: '把远方拆成小行动，记录每一次真实进展。'}].map(item => <div key={item.number}><span>{item.number}</span><item.icon size={18}/><h2>{item.title}</h2><p>{item.text}</p></div>)}</div>
    <footer className="observatory-footer"><span>以真实经历为起点，以你的选择为方向。</span><span>LIFELAB / EXPLORE YOUR POSSIBILITIES</span></footer>
  </div>
}

function ProfileView({ run }: { run: Run }) {
  const profile = run.profile
  if (!profile) return null
  const facts = [
    profile.education && { label: '当前阶段', ...profile.education },
    profile.major && { label: '专业背景', ...profile.major },
    profile.year && { label: '年级', ...profile.year },
    profile.career_stage && { label: '当前阶段', ...profile.career_stage },
    { label: '目标方向', ...profile.target },
    ...profile.constraints.map(fact => ({ label: '现实约束', ...fact })),
  ].filter(Boolean) as { label: string; value: string; source_text: string }[]
  return <section className="profile-section">
    <div className="section-heading"><h2><Sparkles size={17} />对你问题的理解</h2><span>已提取信息</span></div>
    <div className="profile-facts">{facts.map((fact, index) =>
      <div key={index} title={'原话依据 · ' + fact.source_text}><span>{fact.label}</span><strong>{fact.value}</strong></div>)}</div>
    <p className="decision">{profile.decision_question}</p>
  </section>
}

function Clarification({ run }: { run: Run }) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const cache = useQueryClient()
  const clarification = run.clarification!
  const resume = useMutation({
    mutationFn: () => api.resume(run.id, clarification.id, answers),
    onSuccess: () => { cache.invalidateQueries({ queryKey: ['run', run.id] }); cache.invalidateQueries({ queryKey: ['history'] }) },
  })
  return <form className="clarification" onSubmit={event => { event.preventDefault(); resume.mutate() }}>
    <span className="clarification-icon"><MessageSquare size={20} /></span>
    <h2>补充一点信息，让探索更贴近你</h2>
    <p>这些信息会帮助确定检索方向，暂不确定也可以直接写下来。</p>
    {clarification.questions.map(question =>
      <label key={question.id}>{question.question}<small>{question.reason}</small>
        <textarea required maxLength={2000} value={answers[question.id] || ''} placeholder="写下你的情况，或填写“暂不确定”"
          onChange={event => setAnswers(previous => ({ ...previous, [question.id]: event.target.value }))} />
      </label>)}
    <Button type="submit" disabled={resume.isPending || clarification.questions.some(q => !answers[q.id]?.trim())}>
      {resume.isPending ? <LoaderCircle size={16} className="spin" /> : <>继续探索<ArrowRight size={16} /></>}
    </Button>
    {resume.error && <p className="inline-error" role="alert">{resume.error.message}</p>}
  </form>
}

function CaseCard({ item, onEvidence }: { item: Case; onEvidence: (item: Case) => void }) {
  return <article className="case-card">
    <div className="case-source"><span className="zhihu-symbol">{item.source.source_type==='lifelab'?'人':'知'}</span><span>{item.source.author || '知乎内容作者'}</span>
      <span className="source-nature">{item.source_nature === 'self_report' ? '作者自述' : item.source_nature === 'third_party' ? '他人转述' : '信息待核实'}</span>
    </div>
    <h3>{item.title}</h3>
    <div className="case-score">
      {item.matching ? <><strong>{item.matching.score}<small> 匹配分</small></strong>
        <span>{item.matching.tier_label}</span><span>评分字段覆盖 {item.matching.field_coverage}%</span></>
        : <span>历史案例 · 未评分</span>}
    </div>
    {!item.matching && item.background_match && <div className={'case-match match-' + item.background_match}>
      {{ close: '背景接近', partial: '部分背景相近', distant: '背景差异较大', unknown: '背景信息不足' }[item.background_match]}
    </div>}
    {(item.matching ? ['major', 'education', 'target', 'plans', 'actions', 'stage_outcomes'] : ['person_context', 'actions', 'stage_outcomes']).map(field =>
      <div className="case-fact" key={field}><span>{factLabels[field]}</span><p>{item.facts[field]?.value || '摘要未交代'}</p></div>)}
    {item.applicability && <p className="applicability">{item.applicability}</p>}
    {item.background_differences?.length ? <p className="case-differences">{item.background_differences.join('；')}</p> : null}
    <p className="evidence-availability">{Object.keys(item.facts).map(field => factLabels[field] || field).join('、')}有引用</p>
    {item.matching && <details className="match-details"><summary>查看评分依据</summary>
      {item.matching.dimensions.map(dimension => <div className="match-dimension" key={dimension.dimension}>
        <strong>{dimension.label}<span>{dimension.weight ? `权重 ${dimension.weight.toFixed(1)}% · ${dimension.level === null ? '信息未知' : dimension.level * 100 + '% 匹配'} · 得分 ${dimension.contribution.toFixed(2)}` : '本次未启用'}</span></strong>
        <p>{dimension.reason}</p>
      </div>)}
    </details>}
    <div className="case-footer">
      <button onClick={() => onEvidence(item)}><BookOpen size={14} />查看字段证据<ArrowRight size={14} /></button>
      {item.source.url && <a href={item.source.url} target="_blank" rel="noreferrer">阅读原文<ExternalLink size={13} /></a>}
    </div>
  </article>
}

function EvidenceDrawer({ item, run, close }: { item: Case; run: Run; close: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeRef.current?.focus()
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
      if (event.key === 'Tab') {
        const focusable = panelRef.current?.querySelectorAll<HTMLElement>('button, a[href]')
        if (!focusable?.length) return
        const first = focusable[0]
        const last = focusable[focusable.length - 1]
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault(); last.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault(); first.focus()
        }
      }
    }
    document.addEventListener('keydown', handler)
    return () => {
      document.removeEventListener('keydown', handler)
      document.body.style.overflow = overflow
      previous?.focus()
    }
  }, [close])
  return <div className="drawer-overlay" onClick={close}>
    <section ref={panelRef} className="evidence-drawer" role="dialog" aria-modal="true" aria-label="案例来源证据" onClick={event => event.stopPropagation()}>
      <div className="drawer-heading"><span><BookOpen size={18} />来源与字段证据</span>
        <Button ref={closeRef} aria-label="关闭证据详情" variant="ghost" size="icon" onClick={close}><X size={19} /></Button></div>
      <h2>{item.title}</h2>
      <p className="muted">{item.source.source_type==='lifelab'?'以下引用来自用户审阅并授权分享的匿名经历。':'以下引用来自已保存的知乎搜索摘要。'}</p>
      {item.matching && <section className="score-evidence"><h3>匹配评分与引用</h3>
        <p className="muted">总匹配分 {item.matching.score}，评分字段覆盖 {item.matching.field_coverage}%。</p>
        {item.matching.dimensions.filter(dimension => dimension.weight > 0).map(dimension => <div className="match-dimension" key={dimension.dimension}>
          <strong>{dimension.label} · {dimension.level === null ? '未知' : dimension.level * 100 + '% 匹配'} · 得分 {dimension.contribution.toFixed(2)}</strong>
          <p>你的信息 · {dimension.user_facts.map(fact => fact.value).join('、')}</p><p>{dimension.reason}</p>
          {dimension.evidence_fields.map(field => item.facts[field] && <blockquote key={field}>{item.facts[field].quote}</blockquote>)}
        </div>)}
      </section>}
      {Object.entries(item.facts).map(([field, fact]) => {
        const hit = run.hits.find(hit => hit.id === fact.hit_id)
        return <div className="evidence-field" key={field}><h3>{factLabels[field]}</h3><p>{fact.value}</p>
          <blockquote>{fact.quote}</blockquote>
          {hit && <a href={hit.source.url} target="_blank" rel="noreferrer">{hit.source.title}<ArrowUpRight size={13} /></a>}
        </div>
      })}
      {item.additional_evidence?.map((fact, index) => <div className="evidence-field" key={'additional-' + index}>
        <h3>{factLabels[fact.field]} · 来源补充描述</h3><p>{fact.value}</p><blockquote>{fact.quote}</blockquote>
      </div>)}
      <a className="source-link" href={item.source.url} target="_blank" rel="noreferrer">{item.source.source_type==='lifelab'?'打开匿名案例':'打开知乎来源'}<ExternalLink size={15} /></a>
    </section>
  </div>
}

function TraceDetails({ event, run }: { event: TraceEvent; run: Run }) {
  const query = run.queries.find(query => query.id === event.query_id)
  const plan = event.payload.plan as { query_text: string; purpose: string; target_gap: string; relaxed_fields: string[]; requested_count?: number; relaxation_reason?: string } | undefined
  const explanation = event.payload.explanation as string | undefined
  const display = query || plan
  return <div className="trace-detail">
    {display && <><p className="query-text">{display.query_text}</p><p>{display.purpose}</p>
      {display.target_gap && <p><span>补查目标</span>{display.target_gap}</p>}
      {display.requested_count && <p>计划返回 {display.requested_count} 条</p>}
      {display.relaxation_reason && <p>扩展原因 · {display.relaxation_reason}</p>}
      {display.relaxed_fields.length > 0 && <p><span>扩展条件</span>{display.relaxed_fields.map(field => ({ major: '专业范围', experience: '已有经验', time: '时间范围' })[field] || field).join('、')}</p>}
    </>}
    {query && <div className="trace-numbers"><span>{query.result_count} 条返回</span><span>{query.duration_ms === null ? '正在请求' : (query.duration_ms / 1000).toFixed(1) + ' 秒'}</span></div>}
    {query?.error && <p className="inline-error">{query.error}</p>}
    {query?.retry_of && <p>失败重试 · 已计入四次请求预算</p>}
    {query && event.event_type === 'search.completed' && <div className="trace-sources">
      {run.hits.filter(hit => hit.query_id === query.id).map(hit => <details key={hit.id}>
        <summary>{hit.source.title}</summary><p>{hit.text || '本条未返回摘要'}</p>
        <a href={hit.source.url} target="_blank" rel="noreferrer">{hit.source.source_type==='lifelab'?'查看匿名案例':'查看知乎来源'}<ExternalLink size={11} /></a>
      </details>)}
    </div>}
    {explanation && <p>{explanation}</p>}
    {event.payload.case_count !== undefined && <p>当前有 {String(event.payload.case_count)} 个案例通过字段证据检查。</p>}
    {event.event_type === 'profile.extracted' && run.profile && <p>{run.profile.decision_question}</p>}
    {event.event_type === 'budget.updated' && <><p>本次模型调用用量 {String(event.payload.tokens)} Token{event.payload.estimated ? '（估算）' : ''}</p>
      {event.payload.input_tokens != null && <p>输入 {String(event.payload.input_tokens)} · 输出 {String(event.payload.output_tokens ?? '未知')}</p>}
      {event.payload.cumulative_tokens != null && <p>累计 {String(event.payload.cumulative_tokens)} Token</p>}
    </>}
    {event.event_type === 'candidates.selected' && <p>待安排来源 {String(event.payload.queued_sources)} 个，按专业、学历与目标优先分析，每批 {String(event.payload.batch_size)} 个。</p>}
    {event.event_type === 'candidates.extracted' && <p>本批提取候选 {String(event.payload.candidate_count)} 个，引用校验过滤字段 {String(event.payload.rejected_fields)} 项。</p>}
    {event.event_type === 'analysis.deferred' && <p>预留 {String(event.payload.reserved_tokens)} Token，待分析来源 {String(event.payload.pending_sources)} 个。</p>}
    {event.event_type === 'coverage.sufficient' && <p>已跳过后续 {String(event.payload.skipped_queries)} 次补查。</p>}
    {event.event_type === 'cases.ranked' && (event.payload.cases as Case[] | undefined)?.map(item => <details key={item.id}>
      <summary>{item.title} · {item.matching?.score} 分</summary>
      {item.matching?.dimensions.filter(dimension => dimension.weight > 0).map(dimension => <p key={dimension.dimension}>{dimension.label} · {dimension.contribution.toFixed(2)} 分 · {dimension.reason}</p>)}
    </details>)}
    {event.event_type === 'node.completed' && event.payload.duration_ms !== undefined && <p>本步骤耗时 {(Number(event.payload.duration_ms) / 1000).toFixed(1)} 秒</p>}
    {event.event_type === 'report.ready' && run.stop_reason && <p>{reasonLabels[run.stop_reason]}</p>}
  </div>
}

function TracePanel({ run, events, connected }: { run: Run; events: TraceEvent[]; connected: boolean }) {
  const received = useRef({ snapshot: run, at: Date.now() })
  if (received.current.snapshot !== run) received.current = { snapshot: run, at: Date.now() }
  const [, tick] = useState(0)
  useEffect(() => {
    if (run.status !== 'running') return
    const id = setInterval(() => tick(value => value + 1), 1000)
    return () => clearInterval(id)
  }, [run.status])
  const duration = run.elapsed_seconds + (run.clock_started_at ? Math.max(0, (Date.now() - received.current.at) / 1000) : 0)
  return <aside className="trace-panel">
    <div className="panel-heading"><span><span className={'live-dot ' + (run.status !== 'running' ? 'idle' : '')} />探索过程</span><small>Agent Trace</small></div>
    <div className="budget-strip">
      <div><span>检索请求</span><strong>{run.request_count}<small> / {run.limits.requests}</small></strong></div>
      <div><span>活跃耗时</span><strong>{Math.floor(duration)}<small> 秒</small></strong></div>
      <div><span>模型用量</span><strong>{(run.tokens_used / 1000).toFixed(1)}<small>k{run.tokens_estimated ? ' 估' : ''}</small></strong></div>
    </div>
    {!connected && !terminal(run) && <div className="connection-note"><WifiOff size={14} />正在重连，任务进度保存在服务端</div>}
    <div className="trace-events" aria-live="polite" aria-relevant="additions">
      {events.map(event => {
        const error = event.event_type.endsWith('failed')
        const working = event.event_type.endsWith('started')
        const waiting = event.event_type === 'clarification.required'
        return <details className={'trace-event ' + (error ? 'trace-error' : '')} key={event.sequence}>
          <summary>
            <span className="trace-marker">{error ? <CircleAlert size={15} /> : waiting ? <MessageSquare size={14} /> : working ? <Circle size={10} /> : <Check size={13} />}</span>
            <span className="trace-event-title">{event.title}</span><time>{timeText(event.occurred_at)}</time><ChevronDown size={12} />
          </summary>
          <TraceDetails event={event} run={run} />
        </details>
      })}
      {!events.length && <div className="trace-loading"><LoaderCircle size={17} className="spin" />正在读取运行轨迹</div>}
    </div>
    {run.status === 'awaiting_input' && <div className="trace-bottom"><MessageSquare size={16} />等待你补充信息，预算计时已暂停。</div>}
    {run.stop_reason && <div className="trace-bottom"><CheckCircle2 size={16} />{reasonLabels[run.stop_reason]}</div>}
  </aside>
}

function RunPage() {
  const { runId = '' } = useParams()
  const cache = useQueryClient()
  const [events, setEvents] = useState<TraceEvent[]>([])
  const [connected, setConnected] = useState(true)
  const [traceOpen, setTraceOpen] = useState(false)
  const [selected, setSelected] = useState<Case | null>(null)
  const [showAllCases, setShowAllCases] = useState(false)
  const closeEvidence = useCallback(() => setSelected(null), [])
  const result = useQuery({
    queryKey: ['run', runId], queryFn: () => api.run(runId),
    refetchInterval: query => query.state.data && terminal(query.state.data) ? false : 2000,
  })
  const settled = result.data ? terminal(result.data) : false
  useEffect(() => {
    setEvents([])
    setSelected(null)
    setShowAllCases(false)
    const stream = new EventSource('/api/runs/' + runId + '/events')
    stream.onopen = () => setConnected(true)
    stream.onerror = () => setConnected(false)
    stream.addEventListener('trace', message => {
      const event = JSON.parse((message as MessageEvent).data) as TraceEvent
      setEvents(previous => previous.some(item => item.sequence === event.sequence)
        ? previous : [...previous, event].sort((a, b) => a.sequence - b.sequence))
      cache.invalidateQueries({ queryKey: ['run', runId] })
      if (event.event_type.startsWith('run.') || event.event_type === 'clarification.required') {
        cache.invalidateQueries({ queryKey: ['history'] })
      }
    })
    stream.addEventListener('settled', () => { setConnected(true); stream.close() })
    return () => stream.close()
  }, [runId, cache])
  const cancel = useMutation({
    mutationFn: () => api.cancel(runId),
    onSuccess: () => { cache.invalidateQueries({ queryKey: ['run', runId] }); cache.invalidateQueries({ queryKey: ['history'] }) },
  })
  if (result.isPending) return <div className="page-loading"><LoaderCircle className="spin" size={22} />正在读取探索记录</div>
  if (result.error) return <div className="page-loading"><CircleAlert size={22} /><p>{result.error.message}</p><Button asChild><Link to="/retrieval">返回检索</Link></Button></div>
  const run = result.data
  return <>
    <div className="retrieval-result-header"><JourneySteps active={0}/><button className="trace-launch" onClick={() => setTraceOpen(true)}><Radio size={14}/>{settled ? '查看探索过程' : '正在观测'}<span>{run.request_count}/{run.limits.requests}</span></button></div>
    <div className="workspace-grid active-workspace">
      <main className="run-workspace">
        {!settled && <div className="run-signal-bar"><span className="signal-pulse"/><span>{events.at(-1)?.title || '正在接收你的探索信号'}</span><button onClick={() => setTraceOpen(true)}>查看实时轨迹<ArrowUpRight size={13}/></button></div>}
        <div className="run-title-row"><span className="eyebrow">OBSERVATION / 这一次探索</span><Status status={run.status} /></div>
        <h1 className="run-question">{run.question}</h1>
        <div className="run-meta"><span><Clock3 size={13} />{new Date(run.created_at * 1000).toLocaleString('zh-CN', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
          {!settled && <button onClick={() => cancel.mutate()} disabled={cancel.isPending}><Square size={12} />停止检索</button>}</div>
        {cancel.error && <p className="inline-error" role="alert">{cancel.error.message}</p>}
        <ProfileView run={run} />
        {settled && run.profile && <PathEntry runId={run.id} />}
        {run.status === 'awaiting_input' && <Clarification key={run.clarification!.id} run={run} />}
        {run.error && <div className="error-banner" role="alert"><CircleAlert size={18} /><span>{run.error}</span></div>}
        {run.report && <section className="report-summary">
          <span className="report-icon"><CheckCircle2 size={21} /></span>
          <div><h2>{run.result_status === 'empty' ? '本次暂未找到可用经历' : run.result_status === 'unavailable' ? '本次检索暂时受限' : '这次探索，找到了这些线索'}</h2>
            <p>{run.workflow_version === 2 ? run.report.summary : `检索返回 ${run.hits.length} 条内容，去重后 ${new Set(run.hits.map(hit => hit.source_id)).size} 个来源，保留 ${run.cases.length} 个经历案例。`}</p><small>{reasonLabels[run.stop_reason || '']}</small></div>
        </section>}
        {run.workflow_version === 2 && run.analysis_stats && <section className="analysis-statistics" aria-label="检索处理统计">
          {([['原始命中', run.analysis_stats.hits], ['来源去重', run.analysis_stats.sources], ['完成分析', run.analysis_stats.analyzed_sources], ['经历候选', run.analysis_stats.candidates], ['保留案例', run.analysis_stats.cases], ['实际引用来源', run.analysis_stats.cited_sources]] as const).map(([label, count]) => <div key={label}><strong>{count}</strong><span>{label}</span></div>)}
          {run.analysis_stats.pending_sources > 0 && <p>还有 {run.analysis_stats.pending_sources} 个来源待完成分析{settled ? '，本次已结束，详情见结束原因。' : '。'}</p>}
        </section>}
        {run.cases.length > 0 && <section className="cases-section">
          <div className="section-heading"><h2><BookOpen size={17} />相关经历</h2><span>{run.cases.length} 个案例 · 可查看证据</span></div>
          <div className="cases-grid">{(showAllCases ? run.cases : run.cases.slice(0, 5)).map(item => <CaseCard key={item.id} item={item} onEvidence={setSelected} />)}</div>
          {run.cases.length > 5 && <Button variant="ghost" className="more-cases" onClick={() => setShowAllCases(previous => !previous)}>{showAllCases ? '收起其他案例' : `查看其余 ${run.cases.length - 5} 个案例`}</Button>}
        </section>}
        {!run.cases.length && run.status === 'running' && <div className="collecting"><span><Search size={22} /></span><h3>正在寻找与你相关的经历</h3><p>点击“查看实时轨迹”，了解查询与来源。</p></div>}
        {run.coverage.length > 0 && <section className="coverage-section">
          <div className="section-heading"><h2>证据覆盖情况</h2><span>点击案例查看适用条件</span></div>
          <div className="coverage-list">{run.coverage.map(item => <div key={item.dimension}><span>{item.label}</span>
            <span className={'coverage-state coverage-' + item.status}>{coverageLabels[item.status]}<small>{item.case_ids.length ? ' · ' + item.case_ids.length + ' 个案例' : ''}</small></span></div>)}</div>
        </section>}
        {run.gaps.length > 0 && <section className="gaps-section"><h2>还需要了解什么</h2>
          {run.gaps.map((gap, index) => <div key={index}><Circle size={8} /><p>{gap.description}</p><span>{gap.kind === 'practice' ? '待实践验证' : '证据待补充'}</span></div>)}</section>}
        {run.report && <p className="report-note">{run.report.evidence_note}</p>}
      </main>
    </div>
    {traceOpen && <Dialog title="观测日志 · Agent Trace" close={() => setTraceOpen(false)}><TracePanel run={run} events={events} connected={connected} /></Dialog>}
    {selected && <EvidenceDrawer item={selected} run={run} close={closeEvidence} />}
  </>
}

function HistoryPage({ history }: { history: RunSummary[] }) {
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all')
  const filtered = history.filter(run => run.question.toLocaleLowerCase().includes(search.toLocaleLowerCase()) && (filter === 'all' || run.status === filter))
  return <main className="history-page"><div className="archive-orbit" aria-hidden="true"><Orbit size={170} strokeWidth={.4}/></div><div className="eyebrow">FLIGHT ARCHIVE / 探索档案</div><h1>每一次思考，<br/><em>都留下自己的轨迹。</em></h1><p className="intro">回到一个念头，继续一段尚未结束的探索。</p>
    <div className="archive-controls"><label><Search size={15}/><input aria-label="搜索探索记录" placeholder="寻找过去的探索…" value={search} onChange={event => setSearch(event.target.value)}/></label><div>{[['all', '全部'], ['finished', '已完成'], ['running', '探索中']].map(([value, label]) => <button key={value} aria-pressed={filter === value} className={filter === value ? 'active' : ''} onClick={() => setFilter(value)}>{label}</button>)}</div></div>
    {!history.length ? <div className="history-placeholder"><History size={30} /><h2>还没有探索记录</h2><Button asChild><Link to="/retrieval">开始第一次探索<ArrowRight size={16} /></Link></Button></div>
      : <div className="history-table">{filtered.map(run => <Link key={run.id} to={'/retrieval/' + run.id}>
        <span className="history-record-icon"><Search size={19} /></span><div><h2>{run.question}</h2><time>{new Date(run.created_at * 1000).toLocaleString('zh-CN')}</time></div>
        <Status status={run.status} /><ArrowRight size={18} />
      </Link>)}</div>}
    {!!history.length && !filtered.length && <p className="archive-empty">没有找到符合条件的探索，试试其他关键词。</p>}
  </main>
}

export default function App() {
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()
  const exploring = location.pathname.startsWith('/explore/')
  const sharing=location.pathname.startsWith('/shared-cases/')
  const history = useQuery({ queryKey: ['history'], queryFn: api.list, refetchInterval: 10000, enabled: !exploring && !sharing })
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15000, enabled: !exploring && !sharing })
  useEffect(() => { setMenuOpen(false); window.scrollTo({top: 0}) }, [location.pathname])
  useEffect(() => {
    if (!menuOpen) return
    const previous = document.activeElement as HTMLElement | null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    document.querySelector<HTMLElement>('.sidebar a')?.focus()
    const close = (event: KeyboardEvent) => {if (event.key === 'Escape') setMenuOpen(false)}
    window.addEventListener('keydown', close)
    return () => {window.removeEventListener('keydown', close); document.body.style.overflow = overflow; previous?.focus()}
  }, [menuOpen])
  if (exploring) return <><Starfield/><Routes><Route path="/explore/:runId" element={<PathsPage />} /></Routes></>
  if (sharing) return <><Starfield/><Routes><Route path="/shared-cases/:caseId" element={<SharedCasePage/>}/></Routes></>
  return <><Starfield/><div className="app-shell">
    {menuOpen && <button className="mobile-overlay" aria-label="关闭导航" onClick={() => setMenuOpen(false)} />}
    <div id="main-navigation" className={menuOpen ? 'sidebar-wrap open' : 'sidebar-wrap'}><Sidebar history={history.data || []} close={() => setMenuOpen(false)} /></div>
    <div className="app-body" inert={menuOpen}>
      <header className="topbar"><button className="menu-toggle" aria-label="打开导航" aria-expanded={menuOpen} aria-controls="main-navigation" onClick={() => setMenuOpen(true)}><Menu size={21} /></button>
        <span className="breadcrumb"><span className="breadcrumb-caption">WORKSPACE</span><span>/</span><strong>{location.pathname === '/history' ? '探索档案' : '深空观测站'}</strong></span>
        <div className="topbar-right"><span className="connection-status"><i/>{health.isError ? '连接恢复中' : health.data ? '观测站已连接' : '连接观测站'}</span><span className="model-label"><Sparkles size={13} />DeepSeek Flash</span><ThemeToggle/><span className="profile-monogram">L</span></div>
      </header>
      {health.isError && <div className="config-banner error-banner"><WifiOff size={16} />暂时无法连接后端，请确认检索服务已启动。</div>}
      {health.data && (!health.data.model_configured || !health.data.zhihu_configured) && <div className="config-banner">
        <CircleAlert size={17} /><span>{!health.data.model_configured ? 'DeepSeek 模型尚未配置' : '知乎搜索尚未配置'}。请在项目 .env 中填写对应凭证后开始探索。</span>
      </div>}
      <Routes>
        <Route path="/" element={<Navigate to="/retrieval" replace />} />
        <Route path="/retrieval" element={<NewRun health={health.data} />} />
        <Route path="/retrieval/:runId" element={<RunPage />} />
        <Route path="/history" element={<HistoryPage history={history.data || []} />} />
        <Route path="*" element={<Navigate to="/retrieval" replace />} />
      </Routes>
    </div>
  </div></>
}
