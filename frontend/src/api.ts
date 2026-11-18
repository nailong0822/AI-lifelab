import type { Health, Run, RunSummary } from './types'

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch('/api' + path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options?.headers },
  })
  const body = await response.json()
  if (!response.ok) {
    throw new Error(typeof body.detail === 'string' ? body.detail : '请求未完成，请检查输入或稍后重试')
  }
  return body as T
}

export const api = {
  health: () => request<Health>('/health'),
  list: () => request<RunSummary[]>('/runs'),
  run: (id: string) => request<Run>('/runs/' + id),
  create: (question: string) => request<Run>('/runs', {
    method: 'POST', body: JSON.stringify({ question }),
  }),
  resume: (id: string, clarification_id: string, answers: Record<string, string>) =>
    request<Run>('/runs/' + id + '/resume', {
      method: 'POST', body: JSON.stringify({ clarification_id, answers }),
    }),
  cancel: (id: string) => request<Run>('/runs/' + id + '/cancel', { method: 'POST' }),
}
