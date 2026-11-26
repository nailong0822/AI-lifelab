import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.auth import COOKIE_NAME, AuthStore, model_owner
from backend.config import ROOT, Settings
from backend.companion_models import CompanionMessage
from backend.experience_models import JourneyFinish
from backend.store import encode
from backend.user_model import UserModelRouter
from auth_helpers import login_test_client
from test_retrieval import FakeModel, FakeSearch, QUESTION, profile


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(dir=ROOT/'.data',prefix='auth-test-')
        self.settings=Settings(data_dir=Path(self.directory.name))
        self.app=create_app(self.settings,model=FakeModel(),search=FakeSearch())
        self.context=TestClient(self.app)
        self.client=self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None,None,None)
        self.directory.cleanup()

    def register(self,name='alice',role='user',invitation=''):
        response=self.client.post('/api/auth/register',json={
            'username':name,'password':'test-pass-123','role':role,'invitation':invitation})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def root(self):
        login_test_client(self.client)

    def test_registration_roles_sessions_and_key_encryption(self):
        self.assertEqual(self.client.get('/api/runs').status_code,401)
        self.assertIsNone(self.client.get('/api/auth/me').json())
        self.assertEqual(self.client.post('/api/auth/register',json={
            'username':'ailifelab','password':'test-pass-123'}).status_code,422)
        self.assertEqual(self.client.post('/api/auth/register',json={
            'username':'intruder','password':'test-pass-123','role':'superadmin'}).status_code,422)
        alice=self.register()
        cookie=self.client.cookies.get(COOKIE_NAME)
        self.assertTrue(cookie)
        self.assertFalse(self.client.get('/api/health').json()['model_configured'])
        self.assertEqual(self.client.post('/api/runs',json={'question':QUESTION}).status_code,503)
        key='sk-alice-personal-secret'
        saved=self.client.put('/api/auth/model-key',json={'api_key':key})
        self.assertTrue(saved.json()['has_api_key'])
        self.assertNotIn(key,saved.text)
        self.assertEqual(self.app.state.auth.api_key(alice['id']),key)
        with self.app.state.store.connection() as db:
            row=db.execute('SELECT password_hash,model_key FROM users WHERE id=?',(alice['id'],)).fetchone()
        self.assertNotIn('test-pass-123',row[0])
        self.assertNotIn(key,row[1])
        invalid=self.client.put('/api/auth/model-key',json={'api_key':'sk-private invalid'})
        self.assertEqual(invalid.status_code,422)
        self.assertNotIn('sk-private invalid',invalid.text)
        self.assertEqual(AuthStore(self.app.state.store).api_key(alice['id']),key)
        self.assertEqual(self.client.get('/api/admin/users').status_code,403)
        self.assertEqual(self.client.put('/api/auth/model-key',headers={'Origin':'https://other.example'},
                                        json={'api_key':'sk-unwanted'}).status_code,403)
        self.client.post('/api/auth/logout')
        self.assertIsNone(self.app.state.auth.authenticate(cookie))
        self.assertEqual(self.client.get('/api/runs').status_code,401)
        self.assertEqual(self.client.post('/api/auth/login',json={
            'username':'alice','password':'wrong-password'}).status_code,401)
        self.assertEqual(self.client.post('/api/auth/login',json={
            'username':'ALICE','password':'test-pass-123'}).status_code,200)
        self.client.delete('/api/auth/model-key')
        self.assertFalse(self.client.get('/api/health').json()['model_configured'])
        self.assertEqual(self.client.post('/api/auth/register',json={
            'username':'helper','password':'test-pass-123','role':'admin','invitation':'wrong'}).status_code,403)
        helper=self.register('helper','admin','lbrnb666')
        self.assertEqual(helper['role'],'admin')
        stats=self.client.get('/api/admin/users').json()['stats']
        self.assertEqual(stats,{'users':3,'ordinary':1,'admins':2,'today':3})
        self.root()
        with self.app.state.store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users WHERE role='superadmin'").fetchone()[0],1)

    def test_all_private_resource_routes_are_owner_scoped_even_for_administrators(self):
        alice=self.register()
        source=self.app.state.store.create(QUESTION,self.settings,owner_id=alice['id'])
        self.app.state.store.change(source['id'],{'profile':profile(),'status':'finished'})
        path,_=self.app.state.path_store.create(self.app.state.store.get(source['id']),{},[])
        self.app.state.path_store.change(path['id'],{'status':'ready','version':1,'plan':{'route_id':'route-a'}})
        session=self.app.state.companion.store.session(path['id'])
        turn,_=self.app.state.companion.store.new_turn(session['id'],CompanionMessage(
            client_message_id='owner-test-message',text='这是我的私人对话'),80000)
        with self.app.state.store.connection() as db:
            db.execute('INSERT INTO companion_actions VALUES(?,?,?)',('action-a',turn['id'],encode({'id':'action-a','path_id':path['id']})))
            db.execute('INSERT INTO companion_memories VALUES(?,?,?)',('memory-a',path['id'],encode({'id':'memory-a','path_id':path['id']})))
            db.commit()
        body=JourneyFinish(request_id='auth-review-test',version=1,outcome='milestone',reflection='完成了一个实际项目。')
        review,_=self.app.state.experiences.store.create(path['id'],body,{
            'progress_revision':0,'sources':[],'route_id':'route-a','private_text':'private-secret-marker'})
        doc={'title':'完成项目的回顾','summary':'用户最终确认的经历摘要。','fields':{'actions':'完成项目','stage_outcomes':'阶段目标完成'},'lessons':''}
        self.app.state.experiences.store.update(review['id'],lambda item,db:item.update(document=doc,status='draft'))
        urls=[
            '/api/runs/'+source['id'],'/api/runs/'+source['id']+'/report','/api/runs/'+source['id']+'/events',
            '/api/runs/'+source['id']+'/paths','/api/paths/'+path['id'],
            '/api/paths/'+path['id']+'/versions/1','/api/paths/'+path['id']+'/events',
            '/api/paths/'+path['id']+'/companion/memories','/api/paths/'+path['id']+'/experiences',
            '/api/companion/sessions/'+session['id']+'/messages',
            '/api/companion/sessions/'+session['id']+'/events','/api/experiences/'+review['id'],
        ]
        bob=self.register('bob')
        self.assertEqual(self.client.get('/api/runs').json(),[])
        for url in urls:
            self.assertEqual(self.client.get(url).status_code,404,url)
        for method,url,payload in [
            ('post','/api/runs/'+source['id']+'/cancel',{}),
            ('post','/api/paths/'+path['id']+'/companion/sessions',{}),
            ('post','/api/companion/turns/'+turn['id']+'/retry',{}),
            ('post','/api/companion/actions/action-a/respond',{'approve':True}),
            ('patch','/api/companion/memories/memory-a',{'value':'changed'}),
            ('post','/api/experiences/'+review['id']+'/share',{'revision':1,'confirmed':True}),
        ]:
            self.assertEqual(getattr(self.client,method)(url,json=payload).status_code,404,url)
        self.root()
        self.assertEqual(self.client.get('/api/runs/'+source['id']).status_code,404)
        overview=self.client.get('/api/admin/users')
        self.assertEqual(overview.status_code,200,overview.text)
        reviews=self.client.get('/api/admin/users/'+alice['id']+'/reviews')
        self.assertEqual(reviews.status_code,200,reviews.text)
        self.assertEqual(reviews.json()['reviews'][0]['document'],doc)
        self.assertNotIn('private-secret-marker',reviews.text)
        self.assertNotIn('snapshot',reviews.text)
        self.assertNotIn('我的私人对话',reviews.text)
        self.assertEqual(self.client.get('/api/admin/users/'+bob['id']+'/reviews').json()['reviews'],[])
        self.assertEqual(self.client.get('/api/admin/users?search=ALICE').json()['total'],1)

    def test_model_router_uses_separate_keys_for_concurrent_calls(self):
        alice=self.register()
        self.app.state.auth.set_key(alice['id'],'sk-alice-test-secret')
        bob=self.register('bob')
        self.app.state.auth.set_key(bob['id'],'sk-bob-test-secret')
        router=UserModelRouter(self.app.state.auth)
        class Model:
            def __init__(self,api_key):
                self.key=api_key
            async def generate(self,label):
                await asyncio.sleep(.01)
                return label,self.key
            async def choose_tool(self,label):
                await asyncio.sleep(.01)
                return label,self.key
        async def call(owner,label,tool=False):
            token=model_owner.set(owner)
            try:
                return await (router.choose_tool(label) if tool else router.generate(label))
            finally:
                model_owner.reset(token)
        async def main():
            return await asyncio.gather(call(alice['id'],'a'),call(bob['id'],'b'),call(alice['id'],'tool',True))
        with patch('backend.user_model.DeepSeekModel',Model):
            results=asyncio.run(main())
        self.assertEqual(results,[('a','sk-alice-test-secret'),('b','sk-bob-test-secret'),('tool','sk-alice-test-secret')])

    def test_key_connection_test_uses_the_current_users_saved_key(self):
        self.register()
        self.client.put('/api/auth/model-key',json={'api_key':'sk-connection-check'})
        def handler(request):
            self.assertEqual(str(request.url),'https://api.deepseek.com/models')
            self.assertEqual(request.headers['authorization'],'Bearer sk-connection-check')
            return httpx.Response(200,json={'data':[]})
        fake_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch('backend.auth_api.httpx.AsyncClient',return_value=fake_client):
            response=self.client.post('/api/auth/model-key/test')
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn('sk-connection-check',response.text)

    def test_background_retrieval_keeps_its_owner_after_another_account_logs_in(self):
        seen=[]
        auth=self.app.state.auth
        class RecordingModel(FakeModel):
            async def generate(self,*args):
                owner=model_owner.get()
                seen.append((owner,auth.api_key(owner)))
                return await super().generate(*args)
        self.app.state.service.workflow.model.override=RecordingModel()
        alice=self.register()
        auth.set_key(alice['id'],'sk-alice-background')
        first=self.client.post('/api/runs',json={'question':QUESTION})
        self.assertEqual(first.status_code,202,first.text)
        bob=self.register('bob')
        auth.set_key(bob['id'],'sk-bob-background')
        second=self.client.post('/api/runs',json={'question':QUESTION})
        self.assertEqual(second.status_code,202,second.text)
        async def finish():
            await asyncio.gather(*list(self.app.state.service.tasks.values()))
        self.client.portal.call(finish)
        self.assertEqual(self.app.state.store.get(first.json()['id'])['owner_id'],alice['id'])
        self.assertEqual(self.app.state.store.get(second.json()['id'])['owner_id'],bob['id'])
        self.assertEqual(set(seen),{(alice['id'],'sk-alice-background'),(bob['id'],'sk-bob-background')})
        visible=self.client.get('/api/runs').json()
        self.assertEqual([r['id'] for r in visible],[second.json()['id']])

    def test_personal_companion_without_journey_is_private_and_keeps_memory(self):
        asset=self.client.get('/mascot/nailoong-astronaut.png')
        self.assertEqual(asset.status_code,200)
        self.assertEqual(asset.headers['content-type'],'image/png')
        self.assertTrue(asset.content.startswith(b'\x89PNG'))
        self.assertEqual(self.client.get('/mascot/missing.png').status_code,404)
        alice=self.register()
        auth=self.app.state.auth
        auth.set_key(alice['id'],'sk-personal-test-secret')
        seen=[]
        class PersonalModel:
            async def generate(inner,schema,instruction,payload,max_tokens):
                seen.append((model_owner.get(),payload))
                return json.dumps({'intent':'support','message':'我在这里，慢慢说。',
                    'actions':[
                        {'kind':'memory','title':'记住偏好','quote':payload['message'],
                         'value':'回答简短一些','memory_kind':'preference','automatic':True},
                        {'kind':'revision','title':'虚构的调整','quote':payload['message'],
                         'value':'调整一个不存在的计划','automatic':True}]}),{'total_tokens':100}
        self.app.state.companion.model.override=PersonalModel()
        response=self.client.post('/api/companion/personal')
        self.assertEqual(response.status_code,200,response.text)
        session=response.json()['session']['id']
        self.assertEqual(self.client.post('/api/companion/personal').json()['session']['id'],session)
        turn=self.client.post(f'/api/companion/sessions/{session}/messages',json={
            'client_message_id':'personal-1','text':'记住，我希望回答简短一些','web_search':'off'})
        self.assertEqual(turn.status_code,202,turn.text)
        async def settle():
            await asyncio.gather(*list(self.app.state.companion.tasks.values()))
        self.client.portal.call(settle)
        snapshot=self.client.get(f'/api/companion/sessions/{session}/messages').json()
        self.assertEqual(snapshot['turns'][0]['status'],'completed',snapshot)
        self.assertEqual(len(snapshot['memories']),1,snapshot)
        self.assertEqual([a['kind'] for a in snapshot['turns'][0]['actions']],['memory'])
        self.assertEqual(seen[0][0],alice['id'])
        self.assertEqual(seen[0][1]['stage']['tasks'],[])
        self.assertEqual(seen[0][1]['goal'],'')
        memory=snapshot['memories'][0]['id']
        action=snapshot['turns'][0]['actions'][0]['id']
        bob=self.register('bob')
        other=self.client.post('/api/companion/personal').json()['session']['id']
        self.assertNotEqual(session,other)
        self.assertEqual(self.client.get(f'/api/companion/sessions/{session}/messages').status_code,404)
        self.assertEqual(self.client.get(f'/api/companion/sessions/{session}/events').status_code,404)
        self.assertEqual(self.client.post(f'/api/companion/turns/{turn.json()["id"]}/retry').status_code,404)
        self.assertEqual(self.client.post(f'/api/companion/actions/{action}/respond',json={'approve':True}).status_code,404)
        self.assertEqual(self.client.delete(f'/api/companion/memories/{memory}').status_code,404)
        self.client.post('/api/auth/login',json={'username':'alice','password':'test-pass-123'})
        self.assertEqual(self.client.patch(f'/api/companion/memories/{memory}',json={'value':'用中文简短回复'}).status_code,200)
        self.assertEqual(self.client.delete(f'/api/companion/memories/{memory}').status_code,200)
        self.assertEqual(self.client.get('/api/runs').json(),[])

    def test_administrators_default_to_platform_key_without_leaking_to_users(self):
        from fastapi import HTTPException
        auth=self.app.state.auth
        platform=['sk-platform-test-only']
        auth.platform_key=lambda: platform[0]
        alice=self.register()
        self.assertFalse(alice['model_configured'])
        self.assertFalse(self.client.get('/api/health').json()['model_configured'])
        with self.assertRaises(HTTPException):
            auth.api_key(alice['id'])
        admin=self.register('helper','admin','lbrnb666')
        self.assertFalse(admin['has_api_key'])
        self.assertEqual(admin['model_key_source'],'platform')
        self.assertTrue(self.client.get('/api/health').json()['model_configured'])
        self.assertEqual(auth.api_key(admin['id']),platform[0])
        self.assertNotIn(platform[0],self.client.get('/api/auth/me').text)
        self.assertIsNone(admin['key_suffix'])
        def handler(request):
            self.assertEqual(request.headers['authorization'],'Bearer '+platform[0])
            return httpx.Response(200,json={'data':[]})
        with patch('backend.auth_api.httpx.AsyncClient',return_value=httpx.AsyncClient(transport=httpx.MockTransport(handler))):
            self.assertEqual(self.client.post('/api/auth/model-key/test').status_code,200)
        self.client.put('/api/auth/model-key',json={'api_key':'sk-admin-personal-test'})
        self.assertEqual(auth.api_key(admin['id']),'sk-admin-personal-test')
        self.assertEqual(self.client.get('/api/auth/me').json()['model_key_source'],'personal')
        self.client.delete('/api/auth/model-key')
        self.assertEqual(auth.api_key(admin['id']),platform[0])
        root=self.client.post('/api/auth/login',json={'username':'ailifelab','password':'66666666'}).json()
        self.assertEqual(root['model_key_source'],'platform')
        token=model_owner.set(root['id'])
        try:
            with patch('backend.user_model.DeepSeekModel') as model:
                UserModelRouter(auth).resolve()
                model.assert_called_once_with(api_key=platform[0])
        finally:
            model_owner.reset(token)
        platform[0]=''
        self.assertFalse(self.client.get('/api/health').json()['model_configured'])
        with self.assertRaises(HTTPException):
            auth.api_key(root['id'])

    def test_unowned_history_is_migrated_to_the_unique_master_account(self):
        legacy=self.app.state.store.create(QUESTION,self.settings)
        self.app.state.store.change(legacy['id'],{'owner_id':None})
        bob=self.register('bob')
        owned=self.app.state.store.create(QUESTION,self.settings,owner_id=bob['id'])
        restored=AuthStore(self.app.state.store)
        self.assertEqual(self.app.state.store.get(legacy['id'])['owner_id'],restored.master_id)
        self.assertEqual(self.app.state.store.get(owned['id'])['owner_id'],bob['id'])


if __name__=='__main__':
    unittest.main()
