import type { PathRun } from './pathTypes'

export interface JourneyCompletion {key: string; stageId: string; taskId: string; title: string; status: string}

/** Use only current-plan tasks and server-confirmed progress, never inferred milestones. */
export function completionSnapshot(run: Pick<PathRun,'plan'|'progress'>): JourneyCompletion[] {
  return (run.plan?.stages || []).flatMap(stage => stage.tasks.map(task => ({
    key:stage.id+':'+task.id,stageId:stage.id,taskId:task.id,title:task.title,
    status:run.progress[stage.id+':'+task.id]?.status || 'pending',
  })))
}

export function newlyCompleted(previous: JourneyCompletion[] | null, current: JourneyCompletion[]): JourneyCompletion[] {
  if (!previous) return []
  const old=new Map(previous.map(task=>[task.key,task.status]))
  return current.filter(task=>task.status==='completed' && old.has(task.key) && old.get(task.key)!=='completed')
}

export function completionCount(tasks: JourneyCompletion[]): number {
  return tasks.filter(task=>task.status==='completed').length
}
