import { ExternalLink, FileText, Globe2, Search } from 'lucide-react'
import type { CompanionReply, CompanionTurn, WebSource } from '../companionApi'

type WebCitation = NonNullable<CompanionReply['web_citations']>[number]

function sourceStatus(source: WebSource, running: boolean) {
  if (source.read_status === 'read') {
    if (source.is_cited) return '原文已读 · 已引用'
    if (source.in_answer_context) return '原文已读 · 已供回答参考'
    return source.decision_reason ? '原文已读 · '+source.decision_reason : (running ? '原文已读' : '原文已读 · 未供本次回答参考')
  }
  if (source.read_status === 'failed') return '原文读取失败'
  if (source.read_status === 'interrupted') return '原文读取中断'
  return source.decision_reason ? '仅发现链接 · ' + source.decision_reason : '仅发现链接'
}

export function WebResearch({turn, citationsOnly=false}:{turn:CompanionTurn;citationsOnly?:boolean}) {
  const web=turn.web
  if(!web || ['skipped','off','unavailable','pending'].includes(web.status)) return null
  const orderedSources = [...web.sources].sort((a,b) =>
    Number(!!b.is_cited)-Number(!!a.is_cited) || Number(!!b.in_answer_context)-Number(!!a.in_answer_context))
  if(citationsOnly) {
    const groups = new Map<string, {source: WebSource; ids: Set<string>; citations: WebCitation[]}>()
    for (const citation of turn.reply?.web_citations ?? []) {
      const source = web.sources.find(item => item.id === citation.source_id)
      if (!source || !/^https?:\/\//i.test(source.url)) continue
      let group = groups.get(source.url)
      if (!group) {
        group = {source, ids: new Set(), citations: []}
        groups.set(source.url, group)
      }
      group.ids.add(citation.source_id)
      if (source.read_status === 'read') group.source = source
      if (!group.citations.some(item =>
        item.claim === citation.claim && item.quote === citation.quote && item.quote_origin === citation.quote_origin
      )) group.citations.push(citation)
    }
    return <div className="buddy-web-citations">{[...groups].map(([url, {source, ids, citations}]) =>
      <details key={url} className="buddy-web-source">
        <summary>
          <span>{[...ids].join(' / ')}</span>
          {source.kind==='attachment'?<FileText size={13}/>:<Globe2 size={13}/>}
          <strong>{source.title}</strong>
          <small>{source.read_status==='read'?'已读原文':'仅搜索摘要'}</small>
        </summary>
        {citations.map((citation, index) => citation.quote_origin==='title'
          ? <p key={index}>仅引用文件标题</p>
          : <section key={index}>
              <p className="web-supported-claim">{citation.claim}</p>
              <blockquote>{citation.quote}</blockquote>
            </section>
        )}
        <div>
          <a href={url} target="_blank" rel="noreferrer">{source.host}<ExternalLink size={11}/></a>
          <small>{source.published_at?`来源日期（服务估计）：${source.published_at}`:'来源日期未确认'}</small>
        </div>
        <small className="web-retrieved-at">检索于 {new Date(source.retrieved_at*1000).toLocaleString('zh-CN')} · 适用范围与时效以来源原文为准</small>
      </details>
    )}</div>
  }
  return <div className={'buddy-web-research web-'+web.status}>
    <div><Search size={12}/><strong>{['planned','searching'].includes(web.status)?'正在联网查找':web.status==='failed'?'本轮联网未取得充分资料':web.status==='partial'?'联网资料仍有待核实之处':'已完成联网查找'}</strong><small>{web.queries.length} 次搜索 · {web.sources.filter(s=>s.read_status==='read').length} 个来源已读{web.cache_hits?' · 含缓存':''}</small></div>
    {web.warnings.map((warning,i)=><p key={i}>{warning}</p>)}
    {web.queries.length>0 && <details>
      <summary>搜索词与已发现来源</summary>
      <ul>{web.queries.map((query,i)=><li key={i}>{query.query}<small>{query.status==='completed'?'完成':query.status==='started'?'读取中':'未完成'}</small></li>)}</ul>
      {orderedSources.map(source=><a key={source.id} href={source.url} target="_blank" rel="noreferrer">
        <span>{source.id}</span><div>{source.title}{!!source.matched?.length &&
          <div className="web-match-terms">匹配条件 · {source.matched.join('、')}</div>}</div>
        <small>{sourceStatus(source, turn.status==='running')}</small><ExternalLink size={10}/>
      </a>)}
    </details>}
  </div>
}
