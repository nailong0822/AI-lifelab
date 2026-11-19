import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from backend.app import create_app
from backend.config import ROOT, Settings
from backend.store import Store
from backend.path_store import PathStore, PathConflict
from backend.paths import PathWorkflow, PathService
from backend.path_models import PathResponse, ProgressUpdate, PlanRevision
from backend.companion import CompanionService
from backend.companion_models import CompanionMessage
from test_paths import PathModel, QUESTION
from test_retrieval import profile

class CompanionModel(PathModel):
    def __init__(self):
        super().__init__()
        self.inputs = []
        self.fail_once = False
    async def generate(self, schema, instruction, payload, max_tokens):
        if schema.__name__ != 'CompanionReply':
            return await super().generate(schema, instruction, payload, max_tokens)
        self.inputs.append(payload)
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError('synthetic provider failure')
        text = payload['message']
        reply = {'intent': 'support', 'safety': 'normal', 'message': '卡住会让人很挫败。可以先缩小到一个具体输入，我们一起看看实际结果。', 'small_step': '', 'followups': ['卡住时具体出现了什么？'], 'evidence_ids': [], 'actions': []}
        stage = payload['stage']; task = next((t for t in stage['tasks'] if t['id'] == payload['associated_task_id']), stage['tasks'][0])
        if '完成' in text:
            reply.update(intent='progress', message='听到了你的进展，我会按你的反馈核对当前任务。')
            reply['actions'] = [{'kind':'progress','title':'记录当前任务完成','quote':text,'stage_id':stage['id'],'task_id':task['id'],'status':'completed','automatic':'需要确认' not in text}]
        if '记住' in text or '保存偏好' in text:
            reply['actions'] = [{'kind':'memory','title':'记住沟通偏好','quote':text,'value':'回答简短一些','memory_kind':'preference','automatic':'记住' in text}]
        if '调整' in text:
            reply.update(intent='adjustment', actions=[{'kind':'revision','title':'降低后续阶段强度','quote':text,'value':'每周只能投入两小时，请降低后续阶段强度','automatic':False}])
        if '错误引用' in text:
            reply['evidence_ids'] = ['fabricated']
        if '危急测试' in text:
            reply.update(safety='urgent', actions=[{'kind':'memory','title':'不应保存','quote':text,'value':'危机中的推断'}])
        return json.dumps(reply, ensure_ascii=False), {'total_tokens': 200}

class CompanionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / '.data', prefix='companion-test-')
        self.settings = Settings(data_dir=Path(self.directory.name))
        self.business = Store(self.settings.data_dir / 'test.db')
        source = self.business.create(QUESTION, self.settings)
        self.business.change(source['id'], {'profile':profile(), 'status':'finished'})
        self.paths = PathStore(self.business)
        self.model = CompanionModel()
        self.saver_context = AsyncSqliteSaver.from_conn_string(str(self.settings.data_dir / 'checkpoints.db'))
        self.saver = await self.saver_context.__aenter__()
        await self.saver.setup()
        self.path_service = PathService(self.settings, self.paths, PathWorkflow(self.paths, self.model, self.saver))
        run = await self.path_service.create(self.business.snapshot(source['id']))
        self.path_id = run['id']
        for _ in range(500):
            run = self.paths.snapshot(self.path_id)
            if run['status'] == 'awaiting_selection': break
            await asyncio.sleep(.01)
        await self.path_service.respond(self.path_id, PathResponse(input_id=run['input_request']['id'], candidate_id='c1'))
        for _ in range(500):
            run = self.paths.snapshot(self.path_id)
            if run['status'] == 'ready': break
            await asyncio.sleep(.01)
        self.assertEqual(run['status'], 'ready')
        await self.path_service.await_checkpoint(self.path_id)
        self.stage = run['plan']['stages'][0]
        self.service = CompanionService(self.settings, self.paths, self.path_service, self.model, self.saver)
        self.session = self.service.store.session(self.path_id)

    async def asyncTearDown(self):
        await self.service.close()
        await self.path_service.close()
        await self.saver_context.__aexit__(None,None,None)
        self.directory.cleanup()

    async def wait_turn(self, turn_id):
        for _ in range(800):
            task = self.service.tasks.get(turn_id)
            if not task:
                return self.service.store.public_turn(self.service.store.get('turns', turn_id))
            await asyncio.sleep(.01)
        self.fail('Companion operation did not settle')

    async def send(self, text, **kwargs):
        body = CompanionMessage(client_message_id='message-' + str(len(self.service.store.turns(self.session['id'])['turns'])), text=text,
                                stage_id=self.stage['id'], task_id='t1', **kwargs)
        turn = await self.service.send(self.session['id'], body)
        return await self.wait_turn(turn['id'])

    async def test_task_context_and_conversation_survive_restart(self):
        turn = await self.send('虚构测试：我卡在这个实验上了', mode='solve')
        self.assertEqual(turn['status'], 'completed', turn['error'])
        self.assertEqual(self.model.inputs[-1]['associated_task_id'], 't1')
        self.assertIn('completion_criteria', self.model.inputs[-1]['stage']['tasks'][0])
        await self.service.close()
        self.service = CompanionService(self.settings, self.paths, self.path_service, self.model, self.saver)
        await self.service.recover()
        snapshot = self.service.store.snapshot(self.session['id'])
        self.assertEqual(snapshot['turns'][0]['reply']['message'], turn['reply']['message'])
        await self.send('虚构测试：还是刚才的问题')
        self.assertTrue(self.model.inputs[-1]['recent'])

    async def test_explicit_progress_is_atomic_and_can_be_undone(self):
        turn = await self.send('虚构测试：我已经完成了这个实验，日志也保存了')
        action = turn['actions'][0]
        self.assertEqual(action['status'], 'applied', action['error'])
        key = self.stage['id'] + ':t1'
        self.assertEqual(self.paths.get(self.path_id)['progress'][key]['basis'], 'user_report')
        await self.service.undo(action['id'])
        self.assertEqual(self.paths.get(self.path_id)['progress'][key]['status'], 'pending')
        await self.service.undo(action['id'])
        await self.send('虚构测试：接下来如何安排？')
        context = self.model.inputs[-1]
        self.assertEqual(context['task_status'][0]['status'], 'pending')
        self.assertEqual(context['recent'][-1]['operations'][0]['status'], 'undone')

    async def test_negation_future_and_other_people_do_not_complete_tasks(self):
        for text in ['虚构测试：我还没有完成实验', '虚构测试：如果我完成了实验就好了', '虚构测试：我朋友已经完成了实验']:
            turn = await self.send(text)
            self.assertEqual(turn['actions'], [])
        self.assertEqual(self.paths.get(self.path_id)['progress'], {})

    async def test_pending_action_uses_persistent_human_interrupt(self):
        turn = await self.send('虚构测试：我完成了实验，需要确认')
        self.assertEqual(turn['status'], 'awaiting_actions')
        checkpoint = await self.service.graph.aget_state(self.service.config(turn['id']))
        self.assertIn('wait', checkpoint.next)
        await self.service.close()
        self.service = CompanionService(self.settings, self.paths, self.path_service, self.model, self.saver)
        await self.service.recover()
        action = turn['actions'][0]
        await self.service.decide(action['id'], True)
        result = await self.wait_turn(turn['id'])
        self.assertEqual(result['actions'][0]['status'], 'applied', result['actions'][0]['error'])
        revision = self.paths.get(self.path_id)['progress_revision']
        await self.service.decide(action['id'], True)
        self.assertEqual(self.paths.get(self.path_id)['progress_revision'], revision)

    async def test_newer_manual_progress_blocks_old_action(self):
        turn = await self.send('虚构测试：完成了实验，需要确认')
        self.paths.update_progress(self.path_id, ProgressUpdate(stage_id=self.stage['id'], task_id='t1', version=1, status='blocked', note='新的手动记录'))
        await self.service.decide(turn['actions'][0]['id'], True)
        result = await self.wait_turn(turn['id'])
        self.assertEqual(result['actions'][0]['status'], 'failed')
        self.assertEqual(self.paths.get(self.path_id)['progress'][self.stage['id'] + ':t1']['status'], 'blocked')

    async def test_pause_preserves_chat_but_blocks_progress(self):
        self.paths.change(self.path_id, {'journey_status':'paused'})
        turn = await self.send('虚构测试：已经完成了这个实验')
        self.assertIsNotNone(turn['reply'])
        self.assertEqual(turn['actions'][0]['status'], 'failed')
        self.assertEqual(self.paths.get(self.path_id)['progress'], {})

    async def test_listening_does_not_push_unrequested_actions(self):
        turn = await self.send('虚构测试：我完成了实验但还是很累', mode='listen')
        self.assertEqual(turn['actions'], [])

    async def test_explicit_do_not_change_requests_override_model_actions(self):
        turn = await self.send('虚构测试：我完成了实验，但不要替我标记完成')
        self.assertEqual(turn['actions'], [])
        turn = await self.send('虚构测试：不要记住这个沟通偏好')
        self.assertEqual(turn['actions'], [])
        self.assertEqual(self.paths.get(self.path_id)['progress'], {})
        self.assertEqual(self.service.store.memories(self.path_id), [])

    async def test_memories_edit_and_forget_invalidate_old_summary(self):
        turn = await self.send('虚构测试：请记住以后回答简短一些')
        memory = self.service.store.memories(self.path_id)[0]
        self.assertEqual(turn['actions'][0]['status'], 'applied')
        self.service.store.edit_memory(memory['id'], '先倾听，少给清单')
        await self.send('虚构测试：继续聊聊')
        context = self.model.inputs[-1]
        self.assertEqual(context['memories'][0]['value'], '先倾听，少给清单')
        self.assertFalse(any('回答简短' in h['user'] for h in context['recent']))
        self.service.store.edit_memory(memory['id'])
        self.assertEqual(self.service.store.memories(self.path_id), [])

    async def test_optional_memory_can_be_declined(self):
        turn = await self.send('虚构测试：想保存偏好，回答简短一些')
        await self.service.decide(turn['actions'][0]['id'], False)
        result = await self.wait_turn(turn['id'])
        self.assertEqual(result['actions'][0]['status'], 'dismissed')
        self.assertEqual(self.service.store.memories(self.path_id), [])

    async def test_safety_bypass_does_not_push_tasks_or_save_memory(self):
        before = len(self.model.inputs)
        turn = await self.send('虚构安全测试：我现在要自杀')
        self.assertEqual(len(self.model.inputs), before)
        self.assertEqual(turn['reply']['safety'], 'urgent')
        self.assertEqual(turn['actions'], [])
        self.assertEqual(self.service.store.memories(self.path_id), [])
        turn = await self.send('虚构危急测试')
        self.assertEqual(turn['actions'], [])

    async def test_invalid_citations_are_repaired_once_then_fail(self):
        turn = await self.send('虚构测试：错误引用')
        self.assertEqual(turn['status'], 'failed')
        self.assertEqual(len(self.model.inputs), 2)

    async def test_failed_reply_can_retry_without_duplicating_user_message(self):
        self.model.fail_once = True
        turn = await self.send('虚构测试：模型失败后继续')
        self.assertEqual(turn['status'], 'failed')
        await self.service.retry(turn['id'])
        ready = await self.wait_turn(turn['id'])
        self.assertEqual(ready['status'], 'completed', ready['error'])
        self.assertEqual(len(self.service.store.turns(self.session['id'])['turns']), 1)

    async def test_duplicate_send_and_conflicting_payload(self):
        body = CompanionMessage(client_message_id='same-message-id', text='虚构测试：你好')
        first = await self.service.send(self.session['id'], body)
        second = await self.service.send(self.session['id'], body)
        self.assertEqual(first['id'], second['id'])
        await self.wait_turn(first['id'])
        with self.assertRaises(PathConflict):
            await self.service.send(self.session['id'], body.model_copy(update={'text':'不同内容'}))

    async def test_revision_handoff_keeps_plan_until_user_review(self):
        turn = await self.send('虚构测试：每周只能投入两小时，帮我调整计划')
        await self.service.decide(turn['actions'][0]['id'], True)
        result = await self.wait_turn(turn['id'])
        self.assertEqual(result['actions'][0]['status'], 'applied', result['actions'][0]['error'])
        for _ in range(500):
            run = self.paths.get(self.path_id)
            if run['status'] != 'running': break
            await asyncio.sleep(.01)
        self.assertEqual(run['status'], 'awaiting_revision', run['error'])
        self.assertEqual(run['version'], 1)
        await self.path_service.revise(self.path_id, PlanRevision(version=1, instruction='重复操作不应重新生成'), action_id=turn['actions'][0]['id'])
        self.assertEqual(self.paths.get(self.path_id)['status'], 'awaiting_revision')

    async def test_small_budget_stops_before_external_call(self):
        self.service.settings = Settings(data_dir=self.settings.data_dir, companion_tokens=100)
        turn = await self.send('虚构测试：预算不足')
        self.assertEqual(turn['status'], 'failed')
        self.assertFalse(self.model.inputs)

    async def test_undo_does_not_overwrite_later_user_edits(self):
        turn = await self.send('虚构测试：我已经完成了这个实验')
        self.paths.update_progress(self.path_id, ProgressUpdate(stage_id=self.stage['id'], task_id='t1', version=1, status='in_progress', note='用户后来纠正了进度'))
        with self.assertRaises(PathConflict):
            await self.service.undo(turn['actions'][0]['id'])
        self.assertEqual(self.paths.get(self.path_id)['progress'][self.stage['id']+':t1']['note'], '用户后来纠正了进度')

    async def test_new_message_can_follow_pending_action(self):
        first = await self.send('虚构测试：我完成了实验，需要确认')
        second = await self.send('虚构测试：先聊聊另外一个卡点')
        self.assertEqual(second['status'], 'completed')
        await self.service.decide(first['actions'][0]['id'], False)
        settled = await self.wait_turn(first['id'])
        self.assertEqual(settled['status'], 'completed')
        self.assertEqual(len(self.service.store.snapshot(self.session['id'])['turns']), 2)

    async def test_restart_after_confirmation_saved_before_resume(self):
        turn = await self.send('虚构测试：我完成了实验，需要确认')
        action = turn['actions'][0]
        self.service.store.change('turns', turn['id'], {'status':'running', 'decisions':{action['id']:True}})
        await self.service.close()
        self.service = CompanionService(self.settings, self.paths, self.path_service, self.model, self.saver)
        await self.service.recover()
        restored = await self.wait_turn(turn['id'])
        self.assertEqual(restored['actions'][0]['status'], 'applied', restored['error'])

    async def test_initial_dispatch_survives_restart(self):
        body = CompanionMessage(client_message_id='saved-before-dispatch', text='虚构测试：保存后恢复')
        turn, created = self.service.store.new_turn(self.session['id'], body, 12000)
        await self.service.close()
        self.service = CompanionService(self.settings, self.paths, self.path_service, self.model, self.saver)
        await self.service.recover()
        restored = await self.wait_turn(turn['id'])
        self.assertEqual(restored['status'], 'completed', restored['error'])

class CompanionApiTests(unittest.TestCase):
    def test_not_found_and_empty_message_validation(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.data') as folder:
            app = create_app(Settings(data_dir=Path(folder)), model=CompanionModel())
            with TestClient(app) as client:
                self.assertEqual(client.post('/api/paths/missing/companion/sessions').status_code, 404)
                self.assertEqual(client.get('/api/companion/sessions/missing/messages').status_code, 404)
                self.assertEqual(client.post('/api/companion/sessions/missing/messages', json={'client_message_id':'test-client-id','text':''}).status_code, 422)

    def test_http_chat_memory_and_restart_contracts(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.data') as folder:
            settings = Settings(data_dir=Path(folder))
            app = create_app(settings, model=CompanionModel())
            with TestClient(app) as client:
                source = app.state.store.create(QUESTION, settings)
                app.state.store.change(source['id'], {'status':'finished','profile':profile()})
                path = client.post(f"/api/runs/{source['id']}/paths").json()
                def wait(url, predicate):
                    for _ in range(1000):
                        result = client.get(url).json()
                        if predicate(result): return result
                        time.sleep(.01)
                    self.fail('HTTP operation did not settle')
                url = f"/api/paths/{path['id']}"
                path = wait(url, lambda p:p['status']=='awaiting_selection')
                client.post(url+'/respond', json={'input_id':path['input_request']['id'],'candidate_id':'c1'})
                wait(url, lambda p:p['status']=='ready')
                session = client.post(url+'/companion/sessions').json()
                session_id = session['session']['id']
                self.assertEqual(client.post(url+'/companion/sessions').json()['session']['id'],session_id)
                messages_url = f'/api/companion/sessions/{session_id}/messages'
                body = {'client_message_id':'http-memory-message','text':'虚构测试：请记住以后回答简短一些'}
                response = client.post(messages_url,json=body)
                self.assertEqual(response.status_code,202)
                result = wait(messages_url, lambda p:p['turns'] and p['turns'][-1]['status']=='completed')
                self.assertEqual(client.post(messages_url,json=body).json()['id'],response.json()['id'])
                memory = result['memories'][0]
                self.assertEqual(client.patch(f"/api/companion/memories/{memory['id']}",json={'value':'先倾听，不急着列清单'}).status_code,200)
                self.assertEqual(client.get(messages_url).json()['memories'][0]['value'],'先倾听，不急着列清单')
                self.assertEqual(client.delete(f"/api/companion/memories/{memory['id']}").status_code,200)
                events = app.state.companion.store.events(session_id)
                self.assertEqual([e['sequence'] for e in events],list(range(1,len(events)+1)))
            with TestClient(create_app(settings,model=CompanionModel())) as client:
                restored = client.get(messages_url).json()
                self.assertEqual(len(restored['turns']),1)
                self.assertEqual(restored['memories'],[])

if __name__ == '__main__':
    unittest.main()
