import { request } from './api'
export interface CompanionAction {id: string; kind: 'progress'|'revision'|'memory'|'achievement'; title: string; quote: string; value: string; status: string; error: string|null; automatic: boolean; result: {message?: string; changed?: boolean}|null}
export interface WebSource {id:string; title:string; url:string; host:string; published_at:string|null; retrieved_at:number; read_status:string; kind:string; parent_url:string|null; in_answer_context?:boolean; is_cited?:boolean; decision_reason?:string; matched?:string[]}
export interface WebResearch {status:string; warnings:string[]; queries:{query:string; status:string}[]; rounds:number; reads:number; cache_hits:number; sources:WebSource[]}
export interface CompanionReply {intent: string; safety: string; message: string; small_step: string; followups: string[]; evidence_ids: string[]; web_citations?:{source_id:string;quote:string;claim:string;quote_origin?:'passage'|'title'}[]}
export interface CompanionTurn {id: string; ordinal: number; status: string; created_at: number; input: {text: string; mode: string; client_message_id: string}; reply: CompanionReply|null; actions: CompanionAction[]; tokens_used: number; token_limit: number; error: string|null; web?:WebResearch}
export interface CompanionMemory {id: string; kind: string; value: string; updated_at: number; edited_by_user: boolean}
export interface CompanionPage {session: {id: string; path_id: string; mode: 'auto'|'listen'|'solve'; sequence: number}; turns: CompanionTurn[]; memories: CompanionMemory[]; has_older: boolean; oldest_cursor: number|null; capabilities?:{web_search:boolean;provider:string}}
export interface CompanionEvent {sequence: number; title: string; event_type: string; turn_id: string|null; occurred_at: number; payload: Record<string, unknown>}
export const companionApi = {
  personal: () => request<CompanionPage>('/companion/personal', {method:'POST'}),
  session: (pathId: string) => request<CompanionPage>(`/paths/${pathId}/companion/sessions`, {method:'POST'}),
  messages: (id: string, before?: number) => request<CompanionPage>(`/companion/sessions/${id}/messages${before ? '?before='+before : ''}`),
  send: (id: string, body: object) => request<CompanionTurn>(`/companion/sessions/${id}/messages`, {method:'POST',body:JSON.stringify(body)}),
  decide: (id: string, approve: boolean) => request<CompanionPage>(`/companion/actions/${id}/respond`, {method:'POST',body:JSON.stringify({approve})}),
  undo: (id: string) => request<CompanionPage>(`/companion/actions/${id}/undo`, {method:'POST'}),
  retry: (id: string) => request<CompanionTurn>(`/companion/turns/${id}/retry`, {method:'POST'}),
  memory: (id: string, value?: string) => request<{ok: boolean}>(`/companion/memories/${id}`, {method:value === undefined ? 'DELETE' : 'PATCH', ...(value === undefined ? {} : {body:JSON.stringify({value})})}),
}
