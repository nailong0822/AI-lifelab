import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import ts from 'typescript'
const code=ts.transpileModule(readFileSync(new URL('../src/journeyProgress.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
const {completionSnapshot,newlyCompleted,completionCount}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'))
const run=progress=>({plan:{stages:[{id:'a',tasks:[{id:'one',title:'学习'},{id:'two',title:'实践'}]},{id:'b',tasks:[{id:'one',title:'复盘'}]}]},progress})
test('historical completions establish a baseline without a replay',()=>{
  const current=completionSnapshot(run({'a:one':{status:'completed'}}))
  assert.deepEqual(newlyCompleted(null,current),[])
  assert.deepEqual(newlyCompleted(current,structuredClone(current)),[])
})
test('reward only confirmed transitions, with stage-scoped task IDs',()=>{
  const before=completionSnapshot(run({}))
  const after=completionSnapshot(run({'a:one':{status:'completed'},'a:two':{status:'skipped'},'b:one':{status:'completed'}}))
  assert.deepEqual(newlyCompleted(before,after).map(task=>task.key),['a:one','b:one'])
  assert.equal(completionCount(after),2)
})
test('reopening removes a star; completing again is a new transition',()=>{
  const done=completionSnapshot(run({'a:one':{status:'completed'}}))
  const reopened=completionSnapshot(run({'a:one':{status:'pending'}}))
  assert.equal(completionCount(reopened),0)
  assert.deepEqual(newlyCompleted(done,reopened),[])
  assert.equal(newlyCompleted(reopened,done).length,1)
})
test('removed or not-yet-expanded tasks do not create phantom rewards',()=>{
  const current=run({'old:task':{status:'completed'},'a:one':{status:'completed'}})
  assert.equal(completionCount(completionSnapshot(current)),1)
  assert.deepEqual(newlyCompleted([],completionSnapshot(current)),[])
  assert.deepEqual(completionSnapshot({...current,plan:null}),[])
})
