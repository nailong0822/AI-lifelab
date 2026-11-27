import type { PathRun } from './pathTypes'

export interface JourneyTransfer {
  id:string; kind:'stage'|'route'; fromTitle:string; toTitle:string
  fromIndex:number; toIndex:number; destinationStage:string
}

/** Compare persisted positions, never a selected preview or an in-flight API request. */
export function confirmedTransfer(before:PathRun|null|undefined,after:PathRun|null|undefined):JourneyTransfer|null {
  if(!before?.plan||!after?.plan||before.id!==after.id||after.version<before.version)return null
  const fromIndex=before.plan.stages.findIndex(stage=>stage.id===before.current_stage_id)
  const toIndex=after.plan.stages.findIndex(stage=>stage.id===after.current_stage_id)
  if(fromIndex<0||toIndex<0)return null
  const from=before.plan.stages[fromIndex],to=after.plan.stages[toIndex]
  const fromRoute=before.plan.route_id||before.plan.candidate_id
  const toRoute=after.plan.route_id||after.plan.candidate_id
  const routeChanged=!!fromRoute&&!!toRoute&&fromRoute!==toRoute
  if(routeChanged){
    if(after.status!=='ready'||after.error||after.version<=before.version)return null
    return {id:`${after.id}:route:${toRoute}:${after.version}`,kind:'route',fromTitle:before.plan.title,toTitle:after.plan.title,fromIndex,toIndex,destinationStage:to.title}
  }
  // A plan revision or a read-only preview is not a completed-stage departure.
  if(from.id===to.id||toIndex<=fromIndex||after.operation?.kind==='revise'||after.journey_status==='completed'||after.journey_status==='ended')return null
  const complete=from.already_completed||from.tasks.length>0&&from.tasks.every(task=>['completed','skipped'].includes(after.progress[from.id+':'+task.id]?.status||'pending'))
  if(!complete)return null
  return {id:`${after.id}:stage:${from.id}:${to.id}`,kind:'stage',fromTitle:from.title,toTitle:to.title,fromIndex,toIndex,destinationStage:to.title}
}
