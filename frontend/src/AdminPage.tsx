import { useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { request } from './api'
import { AccountControls, useAuth } from './AuthProvider'
import { ThemeToggle } from './ThemeProvider'
import { experienceFields, outcomeLabels } from './experienceApi'
import type { ExperienceDocument } from './experienceApi'
import './admin.css'

interface AdminUser {id:string;username:string;role:string;created_at:number}
interface UsersResult {stats:{users:number;ordinary:number;admins:number;today:number};total:number;page:number;users:AdminUser[]}
interface ReviewsResult {total:number;page:number;reviews:{id:string;outcome:string;status:string;created_at:number;document:ExperienceDocument}[]}
const roles:Record<string,string>={user:'普通用户',admin:'管理员',superadmin:'主管理员'}

export default function AdminPage() {
  const {user}=useAuth()
  const [search,setSearch]=useState('')
  const [page,setPage]=useState(1)
  const [selected,setSelected]=useState<AdminUser|null>(null)
  const [reviewPage,setReviewPage]=useState(1)
  const allowed=!!user && user.role!=='user'
  const users=useQuery({queryKey:['admin-users',search,page],
    queryFn:()=>request<UsersResult>('/admin/users?search='+encodeURIComponent(search)+'&page='+page),
    enabled:allowed,refetchInterval:15000})
  const reviews=useQuery({queryKey:['admin-reviews',selected?.id,reviewPage],
    queryFn:()=>request<ReviewsResult>('/admin/users/'+selected!.id+'/reviews?page='+reviewPage),
    enabled:allowed && !!selected,refetchInterval:15000})
  if(!allowed)return <Navigate to="/retrieval" replace/>
  return <main className="admin-page">
    <header className="admin-nav"><Link to="/retrieval">← 返回主页面</Link><div><ThemeToggle/><AccountControls/></div></header>
    <h1>管理后台</h1>
    {users.data && <div className="admin-stats">{[
      ['注册用户',users.data.stats.users],['普通用户',users.data.stats.ordinary],
      ['管理员',users.data.stats.admins],['今日注册',users.data.stats.today],
    ].map(([label,count])=><section key={label}><strong>{count}</strong><span>{label}</span></section>)}</div>}
    {(users.error || reviews.error) && <p role="alert" className="auth-error">{users.error?.message || reviews.error?.message}</p>}
    <div className="admin-columns"><section className="admin-panel">
      <h2>用户账号</h2>
      <input aria-label="搜索用户名" maxLength={32} placeholder="搜索用户名" value={search} onChange={e=>{setSearch(e.target.value);setPage(1)}}/>
      {users.isLoading && <p role="status">正在加载用户…</p>}
      <div className="admin-user-list">{users.data?.users.map(item=><button key={item.id} className={selected?.id===item.id?'selected':''}
        onClick={()=>{setSelected(item);setReviewPage(1)}}>
        <span><strong>{item.username}</strong><small>{roles[item.role]}</small></span>
        <time>{new Date(item.created_at*1000).toLocaleDateString('zh-CN')}</time>
      </button>)}</div>
      {users.data?.users.length===0 && <p>没有匹配的账号。</p>}
      <div className="admin-pagination"><button disabled={page===1} onClick={()=>setPage(page-1)}>上一页</button>
        <span>第 {page} 页 · {users.data?.total ?? 0} 个账号</span>
        <button disabled={!users.data || page*20>=users.data.total} onClick={()=>setPage(page+1)}>下一页</button></div>
    </section><section className="admin-panel">
      <h2>{selected?selected.username+'的经历复盘':'经历复盘与摘要'}</h2>
      {!selected && <p className="admin-empty">选择账号查看生成的经历复盘。</p>}
      {selected && reviews.isLoading && <p role="status">正在加载复盘…</p>}
      {selected && reviews.data?.reviews.length===0 && <p className="admin-empty">该用户暂未生成经历复盘。</p>}
      {reviews.data?.reviews.map(item=><article key={item.id} className="admin-review">
        <h3>{item.document.title}</h3><small>{outcomeLabels[item.outcome]} · {item.status==='shared'?'已分享':'私人草稿'} · {new Date(item.created_at*1000).toLocaleDateString('zh-CN')}</small>
        <p>{item.document.summary}</p>
        <details><summary>复盘详情</summary>{Object.entries(item.document.fields).filter(([,v])=>v.trim()).map(([field,value])=><div key={field}><h4>{experienceFields[field]}</h4><p>{value}</p></div>)}
          {item.document.lessons && <div><h4>困难、调整与回顾</h4><p>{item.document.lessons}</p></div>}
        </details>
      </article>)}
      {selected && !!reviews.data?.total && <div className="admin-pagination"><button disabled={reviewPage===1} onClick={()=>setReviewPage(reviewPage-1)}>上一页</button>
        <span>第 {reviewPage} 页 · {reviews.data.total} 份复盘</span><button disabled={reviewPage*20>=reviews.data.total} onClick={()=>setReviewPage(reviewPage+1)}>下一页</button></div>}
    </section></div>
  </main>
}
