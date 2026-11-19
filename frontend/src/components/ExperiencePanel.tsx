import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, LoaderCircle, X } from 'lucide-react'
import { experienceApi, experienceFields, outcomeLabels } from '../experienceApi'
import type { ExperienceCase, ExperienceDocument } from '../experienceApi'
import type { PathRun } from '../pathTypes'
import './experiences.css'

export function ExperiencePanel({path,close,refresh}:{path:PathRun;close:()=>void;refresh:()=>void}) {
  const dialog=useRef<HTMLDialogElement>(null)
  const cache=useQueryClient()
  const [selected,setSelected]=useState('')
  const [creating,setCreating]=useState(false)
  const [outcome,setOutcome]=useState(path.journey_status==='completed'?'milestone':'paused')
  const [reflection,setReflection]=useState('')
  const [draft,setDocument]=useState<ExperienceDocument|null>(null)
  const [confirmed,setConfirmed]=useState(false)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const submission=useRef({id:crypto.randomUUID(),signature:''})
  const list=useQuery({queryKey:['experiences',path.id],queryFn:()=>experienceApi.list(path.id),
    refetchInterval:q=>q.state.data?.some(item=>item.status==='generating')?1500:false})
  const caseId=selected || list.data?.[0]?.id || ''
  const detail=useQuery({queryKey:['experience',caseId],queryFn:()=>experienceApi.get(caseId),enabled:!!caseId,
    refetchInterval:q=>q.state.data?.status==='generating'?1500:false})
  const item=detail.data
  useEffect(()=>{
    const el=dialog.current!
    const previous=window.document.body.style.overflow
    window.document.body.style.overflow='hidden'
    el.showModal()
    return ()=>{el.close();window.document.body.style.overflow=previous}
  },[])
  useEffect(()=>{
    setDocument(item?.document ?? null)
    setConfirmed(false)
  },[item?.id,item?.revision,item?.status])
  const update=(value:ExperienceDocument)=>{setDocument(value);setConfirmed(false)}
  async function operate(work:()=>Promise<ExperienceCase>) {
    if(busy)return
    setBusy(true);setError('')
    try {
      const result=await work()
      setSelected(result.id);setCreating(false);setConfirmed(false)
      await cache.invalidateQueries({queryKey:['experiences',path.id]})
      await cache.invalidateQueries({queryKey:['experience',result.id]})
      refresh()
    } catch(e) {
      setError((e as Error).message)
      await cache.invalidateQueries({queryKey:['experience',caseId]})
      await cache.invalidateQueries({queryKey:['experiences',path.id]})
    }
    finally {setBusy(false)}
  }
  async function finish() {
    const signature=JSON.stringify({version:path.version,outcome,reflection})
    if(submission.current.signature!==signature)submission.current={id:crypto.randomUUID(),signature}
    await operate(()=>experienceApi.start(path.id,{request_id:submission.current.id,version:path.version,outcome,reflection}))
  }
  async function save(share=false) {
    if(!item || !draft)return
    await operate(async()=>{
      const changed=JSON.stringify(draft)!==JSON.stringify(item.document)
      const saved=changed || !share?await experienceApi.save(item.id,item.revision,draft):item
      return share?experienceApi.share(saved.id,saved.revision):saved
    })
  }
  const showFinish=creating || (!list.isLoading && list.data?.length===0)
  return <dialog ref={dialog} className="space-dialog experience-dialog" aria-label="我的经历案例"
    onCancel={close} onClick={e=>{if(e.target===e.currentTarget)close()}}>
    <header><h2><BookOpen size={19}/>我的经历案例</h2><button aria-label="关闭" onClick={close}><X size={20}/></button></header>
    <div className="space-dialog-body">
      <fieldset disabled={busy}>
      {(error || list.error || detail.error) && <p className="space-error" role="alert">{error || list.error?.message || detail.error?.message}</p>}
      {list.isLoading && <p role="status"><LoaderCircle className="spin"/>正在读取经历记录</p>}
      {!!list.data?.length && <div className="experience-history">
        <select aria-label="选择案例记录" value={caseId} disabled={busy} onChange={e=>{setSelected(e.target.value);setCreating(false)}}>
          {list.data.map(c=><option key={c.id} value={c.id}>{new Date(c.created_at*1000).toLocaleDateString()} · {c.document?.title || outcomeLabels[c.outcome]}</option>)}
        </select>
        <button disabled={busy || list.data.some(c=>c.status==='generating') || path.status!=='ready'} onClick={()=>setCreating(true)}>重新整理</button>
      </div>}
      {showFinish ? <form onSubmit={e=>{e.preventDefault();void finish()}}>
        <p>结束这段探索，将起点、行动记录和随航对话整理成私人草稿。你可以在审阅后选择匿名分享。</p>
        <label>这段探索的结果<select value={outcome} onChange={e=>setOutcome(e.target.value)}>
          {Object.entries(outcomeLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}
        </select></label>
        <label>实际发生了什么<textarea required minLength={5} maxLength={4000} value={reflection} onChange={e=>setReflection(e.target.value)}
          placeholder="做过哪些行动，遇到了什么困难，实际结果如何？也可以说明尚未完成的目标。"/></label>
        <button className="space-primary" disabled={busy || path.status!=='ready' || reflection.trim().length<5}>
          {busy && <LoaderCircle size={15} className="spin"/>}结束探索并生成私人草稿
        </button>
        {creating && <button type="button" disabled={busy} onClick={()=>setCreating(false)}>返回已有记录</button>}
      </form> : item && <>
        <div className="experience-state"><span>{item.status==='shared'?'已匿名分享':item.status==='generating'?'正在整理':item.status==='failed'?'整理暂未完成':'私人草稿'}</span><span>{outcomeLabels[item.outcome]}</span></div>
        {item.status==='generating' && <div className="experience-progress" role="status"><LoaderCircle className="spin"/><div><strong>{item.phase}</strong><p>关闭窗口后会继续整理，完成后可以回来审阅。</p></div></div>}
        {item.status==='failed' && <div className="space-error"><p>{item.error}</p><button disabled={busy} onClick={()=>void operate(()=>experienceApi.retry(item.id))}>继续整理</button></div>}
        {draft && item.status!=='generating' && <>
          <p className="space-muted">请逐项核对实际经历，并删除姓名、联系方式及不想分享的细节。实际结果来自你的自述。</p>
          <label>标题<input maxLength={100} value={draft.title} onChange={e=>update({...draft,title:e.target.value})}/></label>
          <label>经历摘要<textarea maxLength={2500} value={draft.summary} onChange={e=>update({...draft,summary:e.target.value})}/></label>
          <div className="experience-fields">{Object.entries(experienceFields).map(([key,label])=><label key={key}>{label}
            <textarea maxLength={4000} value={draft.fields[key] || ''} placeholder="未提供，可补充或留空"
              onChange={e=>update({...draft,fields:{...draft.fields,[key]:e.target.value}})}/>
          </label>)}</div>
          <label>困难、调整与回顾<textarea maxLength={1200} value={draft.lessons} onChange={e=>update({...draft,lessons:e.target.value})}/></label>
          <details className="experience-evidence"><summary>核对整理依据 · 仅自己可见</summary>
            {item.facts?.map((fact,index)=><section key={index}><strong>{experienceFields[fact.field]} · {fact.value}</strong>
              {fact.references.map((ref,i)=><blockquote key={i}>{ref.quote}<small>{ref.source_id}</small></blockquote>)}</section>)}
            {!item.facts?.length && <p>当前没有自动提取的证据，请依据实际经历补充。</p>}
          </details>
          <div className="experience-actions">
            <button disabled={busy || draft.title.trim().length<2 || draft.summary.trim().length<5} onClick={()=>void save()}>保存私人草稿</button>
            {item.status==='shared' && <><a href={'/shared-cases/'+item.id} target="_blank" rel="noreferrer">查看分享页面 ↗</a>
              <button disabled={busy} onClick={()=>void operate(()=>experienceApi.withdraw(item.id))}>撤回分享</button></>}
          </div>
          <label className="experience-consent"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>
            <span>我已核对上述内容，同意将这些内容作为匿名经历供其他用户检索。原始对话与私人整理依据保存在本地。</span></label>
          <button className="space-primary" disabled={busy || !confirmed || !draft.fields.actions?.trim() || !draft.fields.stage_outcomes?.trim()}
            onClick={()=>void save(true)}>{busy && <LoaderCircle size={15} className="spin"/>}保存并匿名分享</button>
          <p className="space-muted">修改已分享的案例后，需要重新确认分享。撤回后会从可检索案例库移除。</p>
        </>}
      </>}
      </fieldset>
    </div>
  </dialog>
}

