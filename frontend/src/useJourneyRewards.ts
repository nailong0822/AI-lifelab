import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import type { PathRun } from './pathTypes'
import { completionCount, completionSnapshot, newlyCompleted } from './journeyProgress'
import type { JourneyCompletion } from './journeyProgress'

export interface JourneyReward extends JourneyCompletion {id: string}

export function useJourneyRewards(run: PathRun | null | undefined) {
  const previous=useRef<{scope:string;tasks:JourneyCompletion[]}|null>(null)
  const serial=useRef(0)
  const [queued,setQueued]=useState<JourneyReward[]>([])
  const scope=run?.plan ? run.id+':'+run.version : ''
  useLayoutEffect(()=>{
    if(!run?.plan){previous.current=null;setQueued([]);return}
    const tasks=completionSnapshot(run)
    if(previous.current?.scope!==scope){previous.current={scope,tasks};setQueued([]);return}
    const rewards=newlyCompleted(previous.current.tasks,tasks).map(task=>({...task,id:scope+':'+(++serial.current)}))
    previous.current={scope,tasks}
    const completed=new Set(tasks.filter(task=>task.status==='completed').map(task=>task.key))
    setQueued(old=>[...old.filter(reward=>completed.has(reward.key)),...rewards])
  },[scope,run?.progress,run?.plan])
  const consume=useCallback((id:string)=>setQueued(old=>old.filter(reward=>reward.id!==id)),[])
  const tasks=run ? completionSnapshot(run) : []
  const completed=new Set(tasks.filter(task=>task.status==='completed').map(task=>task.key))
  const rewards=queued.filter(reward=>reward.id.startsWith(scope+':') && completed.has(reward.key))
  return {rewards,consume,totalStars:completionCount(tasks),collectedStars:Math.max(0,completionCount(tasks)-rewards.length)}
}
