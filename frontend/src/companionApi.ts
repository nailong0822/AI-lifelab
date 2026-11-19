import { request } from './api'
export interface CompanionAction {id: string; kind: 'progress'|'revision'|'memory'|'achievement'; title: string; quote: string; value: string; status: string; error: string|null; automatic: boolean; result: {message?: string; changed?: boolean}|null}
export interface CompanionReply {intent: string; safety: string; message: string; small_step: string; followups: string[]; evidence_ids: string[]}
export interface CompanionTurn {id: string; ordinal: number; status: string; created_at: number; input: {text: string; mode: string; client_message_id: string}; reply: CompanionReply|null; actions: CompanionAction[]; tokens_used: number; token_limit: number; error: string|null}
export interface CompanionMemory {id: string; kind: string; value: string; updated_at: number; edited_by_user: boolean}
export interface CompanionPage {session: {id: string; path_id: string; mode: 'auto'|'listen'|'solve'; sequence: number}; turns: CompanionTurn[]; memories: CompanionMemory[]; has_older: boolean; oldest_cursor: number|null}
export interface CompanionEvent {sequence: number; title: string; event_type: string; turn_id: string|null; occurred_at: number; payload: Record<string, unknown>}
export const companionApi = {
  session: (pathId: string) => request<CompanionPage>(`/paths/${pathId}/companion/sessions`, {method:'POST'}),
  messages: (id: string, before?: number) => request<CompanionPage>(`/companion/sessions/${id}/messages${before ? '?before='+before : ''}`),
  send: (id: string, body: object) => request<CompanionTurn>(`/companion/sessions/${id}/messages`, {method:'POST',body:JSON.stringify(body)}),
  decide: (id: string, approve: boolean) => request<CompanionPage>(`/companion/actions/${id}/respond`, {method:'POST',body:JSON.stringify({approve})}),
  undo: (id: string) => request<CompanionPage>(`/companion/actions/${id}/undo`, {method:'POST'}),
  retry: (id: string) => request<CompanionTurn>(`/companion/turns/${id}/retry`, {method:'POST'}),
  memory: (id: string, value?: string) => request<{ok: boolean}>(`/companion/memories/${id}`, {method:value === undefined ? 'DELETE' : 'PATCH', ...(value === undefined ? {} : {body:JSON.stringify({value})})}),
}
