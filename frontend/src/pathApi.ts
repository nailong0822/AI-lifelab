import { request } from './api'
import type { PathRun, Plan } from './pathTypes'
export const pathApi = {
  lookup: (id: string) => request<PathRun | null>(`/runs/${id}/paths`),
  create: (id: string) => request<PathRun>(`/runs/${id}/paths`, {method: 'POST'}),
  get: (id: string) => request<PathRun>(`/paths/${id}`),
  action: (id: string, action: string, body: object = {}, method = 'POST') => request<PathRun>(`/paths/${id}/${action}`, {method, body: JSON.stringify(body)}),
  version: (id: string, version: number) => request<Plan>(`/paths/${id}/versions/${version}`),
}
