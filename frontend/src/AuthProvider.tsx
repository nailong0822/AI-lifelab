import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { KeyRound, LoaderCircle, LogOut, Shield, X } from 'lucide-react'
import { request } from './api'
import { ThemeToggle } from './ThemeProvider'
import { Starfield } from './components/Universe'
import './auth.css'

export interface User {
  id:string; username:string; role:'user'|'admin'|'superadmin'; created_at:number
  has_api_key:boolean; key_suffix:string|null
  model_configured:boolean; model_key_source:'personal'|'platform'|null
}
export const authApi = {
  me:()=>request<User|null>('/auth/me'),
  login:(body:object)=>request<User>('/auth/login',{method:'POST',body:JSON.stringify(body)}),
  register:(body:object)=>request<User>('/auth/register',{method:'POST',body:JSON.stringify(body)}),
  logout:()=>request('/auth/logout',{method:'POST'}),
  saveKey:(api_key:string)=>request<User>('/auth/model-key',{method:'PUT',body:JSON.stringify({api_key})}),
  deleteKey:()=>request<User>('/auth/model-key',{method:'DELETE'}),
  testKey:()=>request<{message:string}>('/auth/model-key/test',{method:'POST'}),
}
interface AuthContextValue {user:User|null; update:(user:User|null)=>void; openKey:()=>void}
const AuthContext=createContext<AuthContextValue|null>(null)

export function useAuth() {
  const value=useContext(AuthContext)
  if(!value)throw new Error('AuthProvider is required')
  return value
}

export function AuthProvider({children}:{children:ReactNode}) {
  const [user,setUser]=useState<User|null>(null)
  const [loading,setLoading]=useState(true)
  const [error,setError]=useState('')
  const [keyOpen,setKeyOpen]=useState(false)
  const cache=useQueryClient()
  const identity=useRef<string|null>(null)
  const epoch=useRef(0)
  const location=useLocation()
  const navigate=useNavigate()
  const applyUser=useCallback((next:User|null)=>{
    if((next?.id ?? null)!==identity.current)cache.clear()
    identity.current=next?.id ?? null
    setUser(next)
    if(!next)setKeyOpen(false)
  },[cache])
  useEffect(()=>{
    let live=true
    const refresh=()=>{
      const version=epoch.current
      void authApi.me().then(value=>{
        if(live && version===epoch.current){applyUser(value);setError('')}
      })
        .catch(e=>{if(live)setError(e.message)}).finally(()=>{if(live)setLoading(false)})
    }
    refresh()
    const expired=()=>{epoch.current++;applyUser(null);cache.clear()}
    const changed=(event:StorageEvent)=>{if(event.key==='lifelab-auth-change')refresh()}
    window.addEventListener('lifelab-unauthorized',expired)
    window.addEventListener('storage',changed)
    window.addEventListener('focus',refresh)
    return ()=>{
      live=false
      window.removeEventListener('lifelab-unauthorized',expired)
      window.removeEventListener('storage',changed)
      window.removeEventListener('focus',refresh)
    }
  },[cache,applyUser])
  const update=(next:User|null)=>{
    epoch.current++
    applyUser(next)
    try {localStorage.setItem('lifelab-auth-change',crypto.randomUUID())} catch { /* Session cookies remain authoritative. */ }
    void cache.invalidateQueries({queryKey:['health']})
  }
  const shared=location.pathname.startsWith('/shared-cases/')
  return <AuthContext.Provider value={{user,update,openKey:()=>setKeyOpen(true)}}>
    {shared?children:loading?<div className="auth-loading" role="status"><LoaderCircle className="spin"/>正在连接</div>
      :user?children:<><Starfield/><LoginForm error={error} signedIn={value=>{update(value);setError('');navigate('/retrieval',{replace:true})}}/></>}
    {keyOpen && user && <ModelKeyDialog close={()=>setKeyOpen(false)}/>}
  </AuthContext.Provider>
}

function LoginForm({signedIn,error:connectionError}:{signedIn:(user:User)=>void;error:string}) {
  const [register,setRegister]=useState(false)
  const [username,setUsername]=useState('')
  const [password,setPassword]=useState('')
  const [confirm,setConfirm]=useState('')
  const [role,setRole]=useState('user')
  const [invitation,setInvitation]=useState('')
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  async function submit() {
    if(busy)return
    if(register && password!==confirm){setError('两次输入的密码不一致');return}
    setBusy(true);setError('')
    try {
      const user=await (register?authApi.register({username,password,role,invitation}):authApi.login({username,password}))
      setPassword('');setConfirm('');setInvitation('');signedIn(user)
    } catch(e){setError((e as Error).message)}
    finally{setBusy(false)}
  }
  return <main className="auth-page"><div className="auth-theme"><ThemeToggle/></div><section className="auth-card">
    <Link className="auth-brand" to="/retrieval">人生实验室</Link>
    <h1>{register?'创建账号':'登录'}</h1>
    <form onSubmit={e=>{e.preventDefault();void submit()}}>
      <fieldset disabled={busy}>
        <label>用户名<input required minLength={3} maxLength={32} autoComplete="username" value={username} onChange={e=>setUsername(e.target.value)}/></label>
        <label>密码<input required minLength={8} maxLength={128} type="password" autoComplete={register?'new-password':'current-password'} value={password} onChange={e=>setPassword(e.target.value)}/></label>
        {register && <>
          <label>确认密码<input required minLength={8} maxLength={128} type="password" autoComplete="new-password" value={confirm} onChange={e=>setConfirm(e.target.value)}/></label>
          <label>账号类型<select value={role} onChange={e=>setRole(e.target.value)}><option value="user">普通用户</option><option value="admin">管理员</option></select></label>
          {role==='admin' && <label>管理员邀请码<input required type="password" maxLength={100} value={invitation} onChange={e=>setInvitation(e.target.value)} autoComplete="off"/></label>}
        </>}
        {(error || connectionError) && <p className="auth-error" role="alert">{error || connectionError}</p>}
        <button className="auth-primary" type="submit">{busy?<LoaderCircle size={17} className="spin"/>:register?'注册并登录':'登录'}</button>
      </fieldset>
    </form>
    <button className="auth-switch" disabled={busy} onClick={()=>{setRegister(!register);setError('');setPassword('');setConfirm('');setInvitation('')}}>{register?'已有账号，去登录':'注册账号'}</button>
  </section></main>
}

export function AccountControls() {
  const {user,update,openKey}=useAuth()
  const navigate=useNavigate()
  const [busy,setBusy]=useState(false)
  if(!user)return null
  return <div className="account-controls">
    <button onClick={openKey}><KeyRound size={15}/><span>模型设置</span>{!user.model_configured && <i aria-label="尚未配置"/>}</button>
    {user.role!=='user' && <Link to="/admin"><Shield size={15}/><span>管理后台</span></Link>}
    <span className="account-name" title={user.username}>{user.username}</span>
    <button aria-label="退出登录" title="退出登录" disabled={busy} onClick={async()=>{
      setBusy(true)
      try {await authApi.logout();update(null);navigate('/retrieval',{replace:true})}
      catch {setBusy(false)}
    }}><LogOut size={15}/></button>
  </div>
}

function ModelKeyDialog({close}:{close:()=>void}) {
  const dialog=useRef<HTMLDialogElement>(null)
  const {user,update}=useAuth()
  const [key,setKey]=useState('')
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [message,setMessage]=useState('')
  useEffect(()=>{
    const element=dialog.current!
    const previous=document.body.style.overflow
    document.body.style.overflow='hidden'
    element.showModal()
    return ()=>{element.close();document.body.style.overflow=previous}
  },[])
  async function action(kind:'save'|'delete'|'test') {
    setBusy(true);setError('');setMessage('')
    try {
      if(kind==='test') {
        if(key.trim()){update(await authApi.saveKey(key.trim()));setKey('')}
        setMessage((await authApi.testKey()).message)
      } else {
        update(await (kind==='save'?authApi.saveKey(key.trim()):authApi.deleteKey()))
        setKey('');setMessage(kind==='save'?'API Key已保存':'API Key已删除')
      }
    } catch(e){setError((e as Error).message)}
    finally{setBusy(false)}
  }
  return <dialog ref={dialog} className="auth-key-overlay" aria-label="模型设置" onCancel={close} onClick={e=>{if(e.target===e.currentTarget)close()}}>
    <section className="auth-card"><header><h2>模型设置</h2><button aria-label="关闭" onClick={close}><X size={19}/></button></header>
      <p>DeepSeek Flash · {user?.role === 'user' ? '所有 AI 操作使用你的个人 API Key。' : user?.model_key_source === 'personal' ? '当前使用个人 API Key，删除后恢复使用服务端 .env 配置。' : user?.model_key_source === 'platform' ? '当前使用服务端 .env 配置的 API Key，无需重复填写。也可保存个人 Key 优先使用。' : '默认使用服务端 .env 的 DEEPSEEK_API_KEY，请在服务端配置，或填写个人 Key。'}</p>
      <form onSubmit={e=>{e.preventDefault();void action('save')}}><fieldset disabled={busy}>
        <label>DeepSeek API Key<input autoFocus type="password" autoComplete="off" minLength={8} maxLength={512} required value={key}
          placeholder={user?.has_api_key?'已保存 · ••••'+user.key_suffix:'填写API Key'} onChange={e=>setKey(e.target.value)}/></label>
        <div className="auth-actions"><button className="auth-primary" type="submit" disabled={key.trim().length<8}>保存</button>
          <button type="button" disabled={!user?.model_configured && key.trim().length<8} onClick={()=>void action('test')}>测试连接</button>
          {user?.has_api_key && <button type="button" onClick={()=>void action('delete')}>删除</button>}</div>
      </fieldset></form>
      {error && <p className="auth-error" role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
    </section>
  </dialog>
}
