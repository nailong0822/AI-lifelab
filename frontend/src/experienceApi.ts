import { request } from './api'

export const experienceFields: Record<string,string> = {
  person_context:'起点背景', major:'专业', education:'学历', year:'年级', career_stage:'职业阶段',
  target:'目标方向', plans:'计划与路径', starting_point:'已有能力', constraints:'现实约束',
  actions:'实际采取的行动', stage_outcomes:'实际结果与当前状态', time_and_cost:'实际投入', event_time:'经历时间',
}
export const outcomeLabels: Record<string,string> = {
  achieved:'达成目标', milestone:'完成阶段目标', changed:'调整方向', paused:'暂停探索', stopped:'结束尝试',
}
export interface ExperienceDocument {
  title:string; summary:string; fields:Record<string,string>; lessons:string
}
export interface ExperienceCase {
  id:string; path_id:string; status:string; outcome:string; revision:number
  document:ExperienceDocument|null; error:string|null; created_at:number; phase:string
  tokens_used:number; source_count:number; processed_batches:number; consented_at:number|null
  facts?:{field:string;value:string;references:{source_id:string;quote:string}[]}[]
}
export interface SharedCase {
  id:string; revision:number; outcome:string; document:ExperienceDocument; shared_at:number; evidence_basis:string
}
export const experienceApi = {
  list:(id:string) => request<ExperienceCase[]>(`/paths/${id}/experiences`),
  get:(id:string) => request<ExperienceCase>(`/experiences/${id}`),
  start:(id:string,body:object) => request<ExperienceCase>(`/paths/${id}/experiences`,{method:'POST',body:JSON.stringify(body)}),
  save:(id:string,revision:number,document:ExperienceDocument) => request<ExperienceCase>(`/experiences/${id}`,{method:'PUT',body:JSON.stringify({revision,document})}),
  share:(id:string,revision:number) => request<ExperienceCase>(`/experiences/${id}/share`,{method:'POST',body:JSON.stringify({revision,confirmed:true})}),
  withdraw:(id:string) => request<ExperienceCase>(`/experiences/${id}/share`,{method:'DELETE'}),
  retry:(id:string) => request<ExperienceCase>(`/experiences/${id}/retry`,{method:'POST'}),
  public:(id:string) => request<SharedCase>(`/shared-cases/${id}`),
}
