import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import ts from 'typescript'
const code=ts.transpileModule(readFileSync(new URL('../src/journeyTransfer.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
const {confirmedTransfer}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))
function run(){return {id:'journey',status:'ready',error:null,version:1,journey_status:'active',current_stage_id:'s1',operation:{kind:'plan'},progress:{'s1:t1':{status:'completed'}},plan:{route_id:'route1',title:'原航线',stages:[{id:'s1',title:'起点',tasks:[{id:'t1'}]},{id:'s2',title:'下一站',tasks:[]},{id:'s3',title:'终点',tasks:[]}]}}}
test('initial load, refresh and repeated polling do not launch a transfer',()=>{
 const current=run()
 assert.equal(confirmedTransfer(null,current),null)
 assert.equal(confirmedTransfer(current,structuredClone(current)),null)
 assert.equal(confirmedTransfer({...current,plan:null},current),null)
 assert.equal(confirmedTransfer(current,{...current,id:'another'}),null)
})
test('a persisted advance launches only when the source tasks are resolved',()=>{
 const before=run(),after={...run(),current_stage_id:'s2',status:'running',operation:{kind:'expand'}}
 assert.equal(confirmedTransfer(before,after)?.kind,'stage')
 assert.equal(confirmedTransfer(before,after)?.toTitle,'下一站')
 assert.equal(confirmedTransfer({...before,progress:{}},{...after,progress:{}}),null)
 assert.equal(confirmedTransfer(after,{...after,status:'ready',version:2}),null)
})
test('coalesced companion updates and skipped tasks follow the saved server position',()=>{
 const before={...run(),progress:{}},after={...run(),current_stage_id:'s2'}
 assert.equal(confirmedTransfer(before,after)?.kind,'stage')
 assert.equal(confirmedTransfer(before,{...after,progress:{'s1:t1':{status:'skipped'}}})?.kind,'stage')
})
test('switching routes waits for a new committed plan, including custom directions',()=>{
 const before=run(),after={...run(),version:2,plan:{...run().plan,route_id:'custom-route',title:'新的探索方向'}}
 assert.equal(confirmedTransfer(before,after)?.kind,'route')
 assert.equal(confirmedTransfer(before,after)?.toTitle,'新的探索方向')
 assert.equal(confirmedTransfer(before,{...after,status:'running'}),null)
 assert.equal(confirmedTransfer(before,{...after,status:'failed',error:'规划失败'}),null)
 assert.equal(confirmedTransfer(before,{...before,status:'running'}),null)
})
test('revisions, final completion and stale versions never invent a departure',()=>{
 const before=run()
 assert.equal(confirmedTransfer(before,{...run(),current_stage_id:'s2',operation:{kind:'revise'},version:2}),null)
 assert.equal(confirmedTransfer(before,{...run(),journey_status:'completed'}),null)
 assert.equal(confirmedTransfer({...before,version:3},{...run(),current_stage_id:'s2',version:2}),null)
})
