from auth_helpers import login_test_client
import asyncio
import copy
import json
import unittest
import tempfile
import time
from pathlib import Path
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.config import ROOT, Settings
from backend.experience_models import JourneyFinish, ExperienceDocument, ExperienceEdit
from backend.experience_store import ExperienceStore, redact
from backend.experiences import ExperienceService
from backend.path_store import PathConflict
from backend.path_models import PathSelection
from backend.service import RetrievalService
from backend.workflow import RetrievalWorkflow
import test_companion as companion_tests
from test_retrieval import FakeModel, FakeSearch, QUESTION, profile
from test_paths import PathModel


class ReviewModel:
    def __init__(self):
        self.calls=[]
        self.fail_compose=False

    async def generate(self,schema,instruction,payload,max_tokens):
        self.calls.append(schema.__name__)
        if schema.__name__=='ExperienceExtraction':
            facts=[]
            for source in payload['sources']:
                text=source['text']
                for field,quote in [('major','生物专业'),('education','研一'),('target','目标是AI Agent实习'),
                                    ('actions','完成了一个项目'),('stage_outcomes','获得面试机会')]:
                    if quote in text:
                        facts.append({'field':field,'value':quote,'references':[{'source_id':source['id'],'quote':quote}]})
            # A fabricated completion with a quote from the plan is rejected.
            plan=next((s for s in payload['sources'] if s['kind']=='plan'),None)
            if plan:
                facts.append({'field':'actions','value':'已经拿到了工作','references':[{'source_id':plan['id'],'quote':plan['text'][:40]}]})
            facts.append({'field':'time_and_cost','value':'三个月','references':[{'source_id':'invented','quote':'虚构时间'}]})
            data={'facts':facts[:30]}
        elif schema.__name__=='ExperienceDocument':
            if self.fail_compose:
                self.fail_compose=False
                raise RuntimeError('transient')
            fields={f['field']:f['value'] for f in payload['facts']}
            fields['time_and_cost']='凭空编造的三个月'
            data={'title':'在读准备开发实习的探索','summary':'保持在读，完成了项目，获得面试机会，最终录用结果未知。',
                  'fields':fields,'lessons':'继续核实自己的实际投入。'}
        else:
            raise AssertionError(schema.__name__)
        return json.dumps(data,ensure_ascii=False),{'total_tokens':180}


class ExperienceTextTests(unittest.TestCase):
    def test_contact_redaction_preserves_public_project_links(self):
        url='https://github.com/example/project'
        self.assertEqual(redact(url),url)
        for value in ['user@example.org','13800138000','https://example.org/file?token=private-value']:
            self.assertNotEqual(redact(value),value)


class ExperienceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=companion_tests.CompanionTests.asyncSetUp
    send=companion_tests.CompanionTests.send
    wait_turn=companion_tests.CompanionTests.wait_turn

    async def asyncTearDown(self):
        if hasattr(self,'experiences'):
            await self.experiences.close()
        if hasattr(self,'retrieval_service'):
            await self.retrieval_service.close()
        await companion_tests.CompanionTests.asyncTearDown(self)

    async def setup_review(self):
        await self.send('我是生物专业研一，目标是AI Agent实习，完成了一个项目，获得面试机会。')
        self.review_model=ReviewModel()
        self.experiences=ExperienceService(self.settings,self.paths,self.service,self.review_model)

    async def finish(self):
        body=JourneyFinish(request_id='finish-journey-test',version=self.paths.get(self.path_id)['version'],
                           outcome='milestone',reflection='完成了一个项目，获得面试机会，尚未拿到实习录用。')
        item=await self.experiences.start(self.path_id,body)
        task=self.experiences.tasks.get(item['id'])
        if task:
            await task
        return self.experiences.store.get(item['id']),body

    async def test_draft_preserves_evidence_and_requires_explicit_publication(self):
        await self.setup_review()
        item,body=await self.finish()
        self.assertEqual(item['status'],'draft',item['error'])
        self.assertNotIn('time_and_cost',item['document']['fields'])
        self.assertNotIn('已经拿到了工作',json.dumps(item['facts'],ensure_ascii=False))
        by_id={s['id']:s for s in item['snapshot']['sources']}
        for fact in item['facts']:
            for ref in fact['references']:
                self.assertIn(ref['quote'],by_id[ref['source_id']]['text'])
                self.assertNotIn(by_id[ref['source_id']]['kind'],('assistant','plan'))
        self.assertEqual(self.experiences.store.search(profile()),[])
        duplicate=await self.experiences.start(self.path_id,body)
        self.assertEqual(duplicate['id'],item['id'])
        self.experiences.store.publish(item['id'],item['revision'])
        public=self.experiences.store.public(item['id'])
        self.assertNotIn('snapshot',public)
        self.assertNotIn('facts',public)
        self.assertNotIn('path_id',public)
        hits=self.experiences.store.search(profile())
        self.assertEqual([h['id'] for h in hits],[item['id']])
        self.assertEqual(self.experiences.store.search(profile(),exclude_path=self.path_id),[])
        await self.experiences.close()
        self.experiences=ExperienceService(self.settings,self.paths,self.service,self.review_model)
        self.assertEqual(self.experiences.store.public(item['id']),public)

    async def test_edit_withdraws_public_copy_and_stale_revision_is_rejected(self):
        await self.setup_review()
        item,_=await self.finish()
        self.experiences.store.publish(item['id'],1)
        changed=copy.deepcopy(item['document'])
        changed['fields']['actions']='完成项目后又做了一次复盘'
        updated=self.experiences.store.save_document(item['id'],ExperienceEdit(revision=1,document=ExperienceDocument(**changed)))
        self.assertEqual(updated['status'],'draft')
        with self.assertRaises(KeyError):
            self.experiences.store.public(item['id'])
        self.assertEqual(self.experiences.store.search(profile()),[])
        with self.assertRaises(PathConflict):
            self.experiences.store.publish(item['id'],1)
        self.experiences.store.publish(item['id'],updated['revision'])
        self.experiences.store.withdraw(item['id'])
        self.assertEqual(self.experiences.store.search(profile()),[])

    async def test_retry_reuses_finished_batches_and_private_records_survive_failure(self):
        await self.setup_review()
        self.review_model.fail_compose=True
        item,_=await self.finish()
        self.assertEqual(item['status'],'failed')
        self.assertIsNotNone(item['document'])
        count=self.review_model.calls.count('ExperienceExtraction')
        await self.experiences.retry(item['id'])
        await self.experiences.tasks[item['id']]
        self.assertEqual(self.experiences.store.get(item['id'])['status'],'draft')
        self.assertEqual(count,self.review_model.calls.count('ExperienceExtraction'))

    async def test_distinct_routes_keep_separate_cases_and_same_route_replaces_its_case(self):
        await self.setup_review()
        first,_=await self.finish()
        self.experiences.store.publish(first['id'],1)
        run=self.paths.get(self.path_id)
        await self.path_service.select(self.path_id,PathSelection(candidate_id='c2',version=run['version']))
        await self.path_service.tasks[self.path_id]
        version=self.paths.get(self.path_id)['version']
        async def another(request_id,reflection):
            result=await self.experiences.start(self.path_id,JourneyFinish(
                request_id=request_id,version=version,outcome='changed',reflection=reflection))
            await self.experiences.tasks[result['id']]
            self.experiences.store.publish(result['id'],1)
            return result['id']
        second=await another('another-route-finish','完成了一个项目，调整了自己的探索方向。')
        self.assertEqual(self.experiences.store.public(first['id'])['id'],first['id'])
        self.assertEqual(self.experiences.store.public(second)['id'],second)
        third=await another('same-route-new-review','完成了一个项目，又做了一次反馈和复盘。')
        self.assertEqual(self.experiences.store.public(first['id'])['id'],first['id'])
        self.assertEqual(self.experiences.store.public(third)['id'],third)
        with self.assertRaises(KeyError):
            self.experiences.store.public(second)

    async def test_publishing_rejects_contact_info_and_supports_paused_outcome(self):
        await self.setup_review()
        body=JourneyFinish(request_id='paused-experience',version=self.paths.get(self.path_id)['version'],
                           outcome='paused',reflection='暂时停止投递，先解决项目质量的问题。')
        item=await self.experiences.start(self.path_id,body)
        await self.experiences.tasks[item['id']]
        self.assertEqual(self.paths.get(self.path_id)['journey_status'],'ended')
        private=self.experiences.store.get(item['id'])
        doc=private['document'];doc['summary']='联系我 user@example.org'
        self.experiences.store.save_document(item['id'],ExperienceEdit(revision=1,document=ExperienceDocument(**doc)))
        with self.assertRaises(PathConflict):
            self.experiences.store.publish(item['id'],2)

    async def test_hybrid_retrieval_scores_shared_cases_and_honors_withdrawal(self):
        await self.setup_review()
        item,_=await self.finish()
        # Use complete literal fields to verify the existing extraction contract.
        doc=item['document']
        doc['fields'].update(education='研究生',person_context='非计算机专业研究生',
                             major='生物专业',target='目标是AI Agent实习',actions='完成了一个项目',
                             stage_outcomes='获得面试机会')
        updated=self.experiences.store.save_document(item['id'],ExperienceEdit(revision=1,document=ExperienceDocument(**doc)))
        self.experiences.store.publish(item['id'],updated['revision'])
        workflow=RetrievalWorkflow(self.business,FakeModel(),FakeSearch(),self.saver)
        workflow.experiences=self.experiences.store
        self.retrieval_service=RetrievalService(self.settings,self.business,workflow)
        created=self.retrieval_service.create(QUESTION)
        await self.retrieval_service.tasks[created['id']]
        run=self.business.snapshot(created['id'])
        self.assertEqual(run['status'],'finished',run['error'])
        internal=[c for c in run['cases'] if c['source'].get('source_type')=='lifelab']
        self.assertTrue(internal)
        self.assertTrue(all(c['matching'] for c in internal))
        self.assertEqual(internal[0]['facts']['actions']['evidence_scope'],'user_confirmed')
        self.assertTrue(any(c['source'].get('source_type')!='lifelab' for c in run['cases']))
        self.experiences.store.withdraw(item['id'])
        current=self.business.snapshot(run['id'])
        self.assertFalse(any(c['source'].get('source_type')=='lifelab' for c in current['cases']))
        self.assertFalse(any(h['source'].get('source_type')=='lifelab' for h in current['hits']))


class ExperienceApiTests(unittest.TestCase):
    def test_http_draft_edit_consent_read_and_withdraw(self):
        class Model:
            def __init__(self):
                self.review=ReviewModel()
                self.paths=PathModel()

            async def generate(self,schema,instruction,payload,max_tokens):
                model=self.review if schema.__name__.startswith('Experience') else self.paths
                return await model.generate(schema,instruction,payload,max_tokens)

        with tempfile.TemporaryDirectory(dir=ROOT/'.data',prefix='experience-api-') as directory:
            settings=Settings(data_dir=Path(directory))
            app=create_app(settings,model=Model(),search=FakeSearch())
            with TestClient(app) as client:
                login_test_client(client)
                original=app.state.store.create(QUESTION,settings)
                app.state.store.change(original['id'],{'profile':profile(),'status':'finished'})
                result=client.post('/api/runs/'+original['id']+'/paths').json()
                path_id=result['id']
                def wait(url,condition):
                    for _ in range(500):
                        value=client.get(url).json()
                        if condition(value):
                            return value
                        time.sleep(.02)
                    self.fail('HTTP background task did not finish')
                path=wait('/api/paths/'+path_id,lambda p:p['status']=='awaiting_selection')
                response=client.post('/api/paths/'+path_id+'/respond',json={
                    'input_id':path['input_request']['id'],'candidate_id':'c1'})
                self.assertEqual(response.status_code,202)
                path=wait('/api/paths/'+path_id,lambda p:p['status']=='ready')
                response=client.post('/api/paths/'+path_id+'/experiences',json={
                    'request_id':'http-finish-test','version':path['version'],'outcome':'milestone',
                    'reflection':'我是生物专业研一，目标是AI Agent实习，完成了一个项目，获得面试机会。'})
                self.assertEqual(response.status_code,202,response.text)
                case_id=response.json()['id']
                case=wait('/api/experiences/'+case_id,lambda c:c['status'] in ('draft','failed'))
                self.assertEqual(case['status'],'draft',case['error'])
                self.assertEqual(client.get('/api/shared-cases/'+case_id).status_code,404)
                self.assertEqual(client.post('/api/experiences/'+case_id+'/share',json={
                    'revision':1,'confirmed':False}).status_code,422)
                shared=client.post('/api/experiences/'+case_id+'/share',json={'revision':1,'confirmed':True})
                self.assertEqual(shared.status_code,200,shared.text)
                public=client.get('/api/shared-cases/'+case_id)
                self.assertEqual(public.status_code,200)
                self.assertEqual(public.headers['cache-control'],'no-store')
                self.assertNotIn('snapshot',public.json())
                self.assertNotIn('request_id',public.json())
                # Early local versions used one public case per path. Preserve
                # consent and the existing FTS row when upgrading that schema.
                with app.state.store.connection() as db:
                    db.executescript("""
                        ALTER TABLE experience_public RENAME TO public_before_downgrade;
                        CREATE TABLE experience_public (
                            id TEXT PRIMARY KEY REFERENCES experience_cases(id),
                            path_id TEXT NOT NULL UNIQUE,revision INTEGER NOT NULL,data TEXT NOT NULL
                        );
                        INSERT INTO experience_public SELECT id,path_id,revision,data FROM public_before_downgrade;
                        DROP TABLE public_before_downgrade;
                    """)
                upgraded=ExperienceStore(app.state.store)
                self.assertEqual(upgraded.public(case_id),public.json())
                self.assertEqual(upgraded.search(profile())[0]['id'],case_id)
                self.assertEqual(client.delete('/api/experiences/'+case_id+'/share').status_code,200)
                self.assertEqual(client.get('/api/shared-cases/'+case_id).status_code,404)
                self.assertEqual(client.get('/api/paths/'+path_id+'/experiences').json()[0]['status'],'draft')


if __name__=='__main__':
    unittest.main()
