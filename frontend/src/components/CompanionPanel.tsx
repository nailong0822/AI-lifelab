import type { ReactNode } from 'react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUp, Check, ChevronLeft, Copy, Globe2, HeartHandshake, LoaderCircle, MessageCircle, Radio, RotateCcw, Sparkles, Star, Trash2, X } from 'lucide-react'
import { companionApi } from '../companionApi'
import type { CompanionAction, CompanionEvent, CompanionTurn } from '../companionApi'
import type { PathRun, PathTask } from '../pathTypes'
import { ThemeToggle } from '../ThemeProvider'
import { WebResearch } from './WebResearch'
import './companion.css'

function ReplyText({text}: {text: string}) {
  const [copied, setCopied] = useState(-1)
  return <>{text.split(/(```[\s\S]*?```)/g).filter(Boolean).map((part, i) => {
    if (!part.startsWith('```')) return <div className="buddy-prose" key={i}>{part}</div>
    const code = part.replace(/^```[^\n]*\n?/, '').replace(/```$/, '')
    return <div className="buddy-code" key={i}><button aria-label="复制代码" onClick={() => {navigator.clipboard.writeText(code).then(() => setCopied(i)).catch(() => setCopied(-1))}}>{copied === i ? <Check size={13}/> : <Copy size={13}/>} {copied === i ? '已复制' : '复制代码'}</button><pre><code>{code}</code></pre></div>
  })}</>
}

export function CompanionPanel({open, path, task, stageId, close, unlink, refreshPath, contextControls}: {
  open: boolean; path: PathRun | null; contextControls?: ReactNode; task: PathTask|null; stageId?: string; close: () => void; unlink: () => void; refreshPath: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const log = useRef<HTMLDivElement>(null)
  const follow = useRef(true)
  const sessionId = useRef('')
  const pending = useRef<{signature: string; body: Record<string, unknown>}|null>(null)
  const cache = useQueryClient()
  const key = ['companion', path?.id || 'personal']
  const [view, setView] = useState<'chat'|'memories'|'trace'>('chat')
  const [draft, setDraft] = useState('')
  const [mode, setMode] = useState<'auto'|'listen'|'solve'>('auto')
  const [webEnabled, setWebEnabled] = useState(true)
  const [sending, setSending] = useState(false)
  const [workingAction, setWorkingAction] = useState('')
  const [error, setError] = useState('')
  const [events, setEvents] = useState<CompanionEvent[]>([])
  const [connected, setConnected] = useState(false)
  const [older, setOlder] = useState<CompanionTurn[]>([])
  const [olderDone, setOlderDone] = useState(false)
  const [editing, setEditing] = useState<{id: string; value: string}|null>(null)
  const query = useQuery({queryKey:key, enabled:open, queryFn:async () => {
    const result = sessionId.current ? await companionApi.messages(sessionId.current) : path ? await companionApi.session(path.id) : await companionApi.personal()
    sessionId.current = result.session.id
    return result
  }, refetchInterval:q => !open ? false : q.state.data?.turns.some(t => t.status === 'running') ? 1200 : 5000})
  const data = query.data
  const session = data?.session.id
  const turns = Array.from(new Map([...older, ...(data?.turns || [])].map(t => [t.id,t])).values()).sort((a,b) => a.ordinal-b.ordinal)
  const running = sending || turns.some(t => t.status === 'running')
  useEffect(() => {
    const element = dialog.current!
    if (!open) {element.close(); return}
    const previous = document.activeElement as HTMLElement | null
    const escape = (event: KeyboardEvent) => {if (event.key === 'Escape') {event.preventDefault(); close()}}
    document.addEventListener('keydown', escape)
    setView('chat')
    element.show()
    return () => {element.close(); document.removeEventListener('keydown', escape); previous?.focus()}
  }, [open])
  useEffect(() => {if (session) setMode(data?.session.mode || 'auto')}, [session])
  useEffect(() => {
    if (!open || !session) return
    const source = new EventSource(`/api/companion/sessions/${session}/events`)
    source.onopen = () => setConnected(true)
    source.onerror = () => setConnected(false)
    source.addEventListener('trace', message => {
      const event = JSON.parse((message as MessageEvent).data) as CompanionEvent
      setEvents(old => old.some(item => item.sequence === event.sequence) ? old : [...old,event].slice(-250))
      cache.invalidateQueries({queryKey:key})
      if (['progress.updated','progress.undone','action.applied'].includes(event.event_type)) refreshPath()
    })
    return () => source.close()
  }, [open,session,path?.id])
  useLayoutEffect(() => {if (open && view === 'chat' && follow.current && log.current) log.current.scrollTop = turns.length ? log.current.scrollHeight : 0}, [data, open, view])
  useEffect(() => {
    if (pending.current && data?.turns.some(t => t.input.client_message_id === pending.current?.body.client_message_id)) {
      const submitted = pending.current.body.text
      setDraft(current => current.trim() === submitted ? '' : current)
      pending.current = null
    }
  }, [data])
  const refresh = () => {void cache.invalidateQueries({queryKey:key}); refreshPath()}
  async function send() {
    if (!session || !draft.trim() || running) return
    const text = draft.trim()
    const payload = {text, mode, web_search:webEnabled?'auto':'off', stage_id:task ? stageId : null, task_id:task?.id || null}
    const signature = JSON.stringify(payload)
    if (!pending.current || pending.current.signature !== signature) pending.current = {signature,body:{...payload,client_message_id:crypto.randomUUID()}}
    const body = pending.current.body
    setSending(true); setError(''); follow.current = true
    try {await companionApi.send(session,body); setDraft(current => current.trim() === text ? '' : current); pending.current = null; refresh()}
    catch(e) {setError((e as Error).message); void query.refetch()}
    finally {setSending(false)}
  }
  async function operate(id: string, operation: () => Promise<unknown>) {
    if (workingAction) return
    setWorkingAction(id); setError('')
    try {await operation(); refresh()} catch(e) {setError((e as Error).message); refresh()} finally {setWorkingAction('')}
  }
  async function loadOlder() {
    if (!session || workingAction) return
    setWorkingAction('older')
    try {
      const before = older.length ? older[0].ordinal : data?.oldest_cursor || undefined
      const page = await companionApi.messages(session, before)
      follow.current = false
      setOlder(old => [...page.turns,...old]); setOlderDone(!page.has_older)
    } catch(e) {setError((e as Error).message)} finally {setWorkingAction('')}
  }
  function ActionCard({action}: {action: CompanionAction}) {
    return <div className={'buddy-action action-' + action.status}><div><span>{({progress:'进展记录',revision:'计划调整',memory:'个人记忆',achievement:'成长成果'})[action.kind]}</span><strong>{action.title}</strong></div><blockquote>“{action.quote}”</blockquote>{action.kind !== 'progress' && action.value && <p>{action.value}</p>}
      {action.status === 'pending' && <div className="buddy-action-buttons"><button disabled={!!workingAction || running} className="buddy-confirm" onClick={() => void operate(action.id, () => companionApi.decide(action.id,true))}>{({progress:'确认记录',revision:'生成调整方案',memory:'保存记忆',achievement:'记录这项成果'})[action.kind]}</button><button disabled={!!workingAction || running} onClick={() => void operate(action.id, () => companionApi.decide(action.id,false))}>暂不执行</button></div>}
      {action.status === 'applied' && <div className="buddy-action-result"><Check size={13}/><span>{action.kind === 'progress' ? '已根据你的反馈更新任务' : action.result?.message || '已保存'}</span>{action.kind === 'progress' && action.result?.changed && <button disabled={!!workingAction} onClick={() => void operate(action.id, () => companionApi.undo(action.id))}><RotateCcw size={12}/>撤销</button>}{action.kind === 'revision' && <button onClick={close}>回星图审阅</button>}</div>}
      {action.status === 'failed' && <p className="buddy-action-error">{action.error}</p>}{action.status === 'dismissed' && <small>已保留原状态</small>}{action.status === 'undone' && <small>这次更新已撤销</small>}
    </div>
  }
  return <dialog id="global-companion-panel" className="companion-dialog" ref={dialog} aria-label="随航伙伴" onCancel={close} onClick={e => {if (e.target === e.currentTarget) close()}}>
    <header className="buddy-header"><img className="buddy-mascot-avatar" src="/mascot/nailoong-astronaut.png" alt="奶龙随航伙伴"/><div><h2>随航伙伴 <small>AI</small></h2><p>一起把下一步，变得轻一点。</p></div><div className="buddy-header-actions"><ThemeToggle/><button className="buddy-close" autoFocus aria-label="关闭随航伙伴" onClick={close}><X size={21}/></button></div></header>
    <nav className="buddy-tabs" aria-label="伙伴功能">{([['chat','一起聊聊',MessageCircle],['memories','个人记忆',HeartHandshake],['trace','运行轨迹',Radio]] as const).map(([value,label,Icon]) => <button key={value} aria-pressed={view === value} className={view === value ? 'active' : ''} onClick={() => setView(value)}><Icon size={14}/>{label}{value === 'memories' && !!data?.memories.length && <small>{data.memories.length}</small>}</button>)}<span>{connected ? '已连接' : '正在重连'}</span></nav>
    {(error || query.error) && <div className="buddy-error" role="alert">{error || query.error?.message}<button onClick={() => {setError(''); void query.refetch()}}>刷新</button></div>}
    {view === 'chat' && <>
      {contextControls}
      {(path || task) && <div className="buddy-context"><span><Star size={12}/>{task ? '正在聊这个任务' : path ? '当前航程' : '随时聊聊'}</span><strong>{task?.title || path?.plan?.title || '日常陪伴'}</strong>{task && <button aria-label="取消关联任务" onClick={unlink}><X size={13}/></button>}{path?.journey_status === 'paused' && <small>航程已暂停，仍可以聊聊</small>}</div>}
      <div className="buddy-messages" ref={log} onScroll={() => {if(log.current) follow.current = log.current.scrollHeight-log.current.scrollTop-log.current.clientHeight < 100}}>
        {query.isPending && <p className="buddy-loading"><LoaderCircle className="spin" size={17}/>正在找回我们的对话…</p>}
        {data?.has_older && !olderDone && <button className="buddy-older" disabled={!!workingAction} onClick={() => void loadOlder()}><ChevronLeft size={12}/>查看更早的对话</button>}
        {data && !turns.length && <div className="buddy-welcome"><p>{task ? `关于“${task.title}”，你可以说说卡在哪里。` : '遇到困难、想分享进展，或只是想说说话，都可以。'}<br/>{path ? '我会结合你的计划，和你一起想办法。' : '不必先决定目的地，我们可以从你想聊的事开始。'}</p><div>{['这一步有点难，帮我拆小一点','先听我说说，今天有点累','我想复盘一下最近的进展'].map(text => <button key={text} onClick={() => {setDraft(text); setView('chat')}}>{text}</button>)}</div></div>}
        {turns.map(turn => <section className="buddy-turn" key={turn.id}><div className="buddy-message buddy-user"><span>你</span><div>{turn.input.text}</div></div>{!turn.reply && <WebResearch turn={turn}/>} {turn.reply && <div className="buddy-message buddy-assistant"><span className="buddy-avatar"><Sparkles size={15}/></span><div><WebResearch turn={turn}/><ReplyText text={turn.reply.message}/><WebResearch turn={turn} citationsOnly/>{turn.reply.small_step && <div className="buddy-small-step"><Star size={14}/><div><strong>可以试试这一小步</strong><p>{turn.reply.small_step}</p></div></div>}{turn.reply.evidence_ids.map(id => {const evidence = path?.evidence_catalog[id]; return evidence && <details className="buddy-evidence" key={id}><summary>这条建议的经历依据</summary><blockquote>{evidence.quote}</blockquote>{evidence.source.url && /^(https?:\/\/|\/shared-cases\/)/.test(evidence.source.url) && <a href={evidence.source.url} target="_blank" rel="noreferrer">查看原始来源 ↗</a>}</details>})}{turn.actions.map(action => <ActionCard key={action.id} action={action}/>)}{turn.reply.followups.length > 0 && turn.id === turns.at(-1)?.id && <div className="buddy-followups">{turn.reply.followups.map(text => <button key={text} disabled={running} onClick={() => setDraft(text)}>{text}</button>)}</div>}<small className="buddy-usage">{turn.tokens_used.toLocaleString()} / {turn.token_limit.toLocaleString()} tokens · {new Date(turn.created_at*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}</small></div></div>}{turn.status === 'failed' && <div className="buddy-turn-error"><p>{turn.error}</p>{!turn.reply && <button disabled={running || !!workingAction} onClick={() => void operate(turn.id, () => companionApi.retry(turn.id))}><RotateCcw size={13}/>重试这条消息</button>}</div>}{turn.status === 'running' && <div className="buddy-thinking" role="status"><span className="buddy-avatar"><Sparkles size={14}/></span><LoaderCircle size={14} className="spin"/>{events.filter(e => e.turn_id === turn.id).at(-1)?.title || '正在整理回应…'}</div>}</section>)}
      </div>
      <form className="buddy-composer" onSubmit={e => {e.preventDefault(); void send()}}><div className="buddy-modes">{([['auto','自在聊聊'],['listen','先听我说'],['solve','一起想办法']] as const).map(([value,label]) => <button key={value} type="button" aria-pressed={mode === value} className={mode === value ? 'active' : ''} onClick={() => setMode(value)}>{label}</button>)}</div><div><textarea aria-label="给随航伙伴的消息" placeholder={mode === 'listen' ? '慢慢说，我在这里听。' : '说说你的感受、困难，或今天的小进展…'} value={draft} maxLength={6000} onChange={e => setDraft(e.target.value)} onKeyDown={e => {if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {e.preventDefault(); void send()}}}/><button className="buddy-send" aria-label="发送消息" disabled={running || !draft.trim() || !session} type="submit">{running ? <LoaderCircle className="spin" size={17}/> : <ArrowUp size={19}/>}</button></div><div className="buddy-composer-footer"><button type="button" className="buddy-web-toggle" aria-label={data?.capabilities?.web_search ? '联网搜索，自动判断' : '联网搜索未配置'} aria-pressed={!!data?.capabilities?.web_search && webEnabled} disabled={!data?.capabilities?.web_search} title={data?.capabilities?.web_search ? '开启后，伙伴按问题需要调用搜索，并展示来源' : '请在服务端 .env 填写 TAVILY_API_KEY 后重启'} onClick={()=>setWebEnabled(!webEnabled)}><Globe2 size={12}/>{data?.capabilities?.web_search ? webEnabled ? '联网 · 自动' : '联网 · 关闭' : '联网未配置'}</button><small>AI 伙伴 · 不替代专业帮助 · 重要决定由你掌舵</small></div></form>
    </>}
    {view === 'memories' && <div className="buddy-secondary"><h3>记住对你有帮助的事。</h3><p>只保留你确认的偏好、能力或约束。这里的记忆用于当前会话，随时可以修改或删除。</p>{!data?.memories.length && <div className="buddy-empty"><HeartHandshake size={30}/><p>还没有保存个人记忆。你可以说：“请记住，我希望你先听我说。”</p></div>}{data?.memories.map(memory => <article className="buddy-memory" key={memory.id}><small>{({preference:'沟通偏好',constraint:'现实约束',ability:'已有能力'} as Record<string,string>)[memory.kind]}</small>{editing?.id === memory.id ? <><textarea aria-label="修改记忆内容" maxLength={500} value={editing.value} onChange={e => setEditing({...editing,value:e.target.value})}/><div><button disabled={!!workingAction || !editing.value.trim()} onClick={() => void operate(memory.id, async () => {await companionApi.memory(memory.id,editing.value); setEditing(null)})}>保存修改</button><button onClick={() => setEditing(null)}>取消</button></div></> : <><p>{memory.value}</p><div><button onClick={() => setEditing({id:memory.id,value:memory.value})}>修改</button><button disabled={!!workingAction} onClick={() => void operate(memory.id, () => companionApi.memory(memory.id))}><Trash2 size={12}/>删除记忆</button></div></>}</article>)}<p className="buddy-footnote">删除记忆会清除关联摘要并停止用于后续回应，聊天记录仍保留。聊天内容和记忆保存在本地数据库。</p></div>}
    {view === 'trace' && <div className="buddy-secondary"><h3>每一步，都有迹可循。</h3><p>这里展示实际工作流事件、操作结果与模型用量，不展示模型内部思考。</p><ol className="buddy-events">{events.map(event => <li key={event.sequence}><small>{new Date(event.occurred_at*1000).toLocaleTimeString('zh-CN')}</small><strong>{event.title}</strong>{Object.keys(event.payload).length > 0 && <details><summary>查看节点数据</summary><pre>{JSON.stringify(event.payload,null,2)}</pre></details>}</li>)}</ol></div>}
  </dialog>
}
