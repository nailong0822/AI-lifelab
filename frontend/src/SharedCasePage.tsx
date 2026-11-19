import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { experienceApi, experienceFields, outcomeLabels } from './experienceApi'
import { ThemeToggle } from './ThemeProvider'
import './components/experiences.css'

export default function SharedCasePage() {
  const {caseId=''}=useParams()
  const result=useQuery({queryKey:['shared-case',caseId],queryFn:()=>experienceApi.public(caseId),
    retry:false,refetchInterval:10000})
  const item=result.data
  if(result.isError)return <main className="shared-experience"><h1>这份案例暂不可查看</h1><p>分享可能已撤回或更新。</p><Link to="/retrieval">返回检索</Link></main>
  return <main className="shared-experience"><div className="experience-actions"><Link to="/retrieval">← 返回人生实验室</Link><ThemeToggle/></div>
    {result.isLoading && <p role="status">正在读取匿名经历…</p>}
    {item && <><h1>{item.document.title}</h1><p>{outcomeLabels[item.outcome]} · {item.evidence_basis}</p>
      <section><h2>经历回顾</h2><p>{item.document.summary}</p></section>
      {Object.entries(item.document.fields).filter(([,value])=>value.trim()).map(([key,value])=><section key={key}><h2>{experienceFields[key]}</h2><p>{value}</p></section>)}
      {item.document.lessons && <section><h2>困难、调整与回顾</h2><p>{item.document.lessons}</p></section>}
      <p>分享于 {new Date(item.shared_at*1000).toLocaleDateString()}。这是本人确认的经历自述，结果与适用条件需要结合个人情况判断。</p>
    </>}
  </main>
}
