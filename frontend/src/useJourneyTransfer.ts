import {useCallback,useLayoutEffect,useRef,useState} from 'react'
import type {PathRun} from './pathTypes'
import {confirmedTransfer} from './journeyTransfer'
import type {JourneyTransfer} from './journeyTransfer'

export function useJourneyTransfer(run:PathRun|null|undefined){
  const previous=useRef<PathRun|null|undefined>(undefined)
  const seen=useRef(new Set<string>())
  const [transfer,setTransfer]=useState<JourneyTransfer|null>(null)
  useLayoutEffect(()=>{
    if(previous.current?.id!==run?.id){setTransfer(null);seen.current.clear()}
    if(run&&previous.current?.id===run.id&&run.version<previous.current.version)return
    const next=confirmedTransfer(previous.current,run)
    previous.current=run
    if(next&&!seen.current.has(next.id)){
      seen.current.add(next.id)
      if(!document.hidden)setTransfer(next)
    }
  },[run])
  const finish=useCallback((id:string)=>setTransfer(current=>current?.id===id?null:current),[])
  return {transfer,finish}
}
