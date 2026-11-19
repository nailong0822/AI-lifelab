import copy
import unittest
from types import SimpleNamespace
from backend.companion import CompanionService, INSTRUCTION, WEB_RESPONSE_INSTRUCTION
from backend.companion_models import CompanionReply
from backend.providers import ProviderError
from backend.config import Settings
from backend.web_context import fit_web_context, citation_numbers_supported, original_quote
from backend.web_search import WebSearchTool
from backend.web_models import SearchConstraint, WebSearchArgs
from backend.web_relevance import excerpt, grounded_constraints, relevance


def web_fixture():
    sources=[{'id':'W01','title':'乙机构接收方案','url':'https://example.org/other','host':'example.org','score':.95,
        'read_status':'read','content':'乙机构的旧方案与本次目标不一致。'*140,'snippet':'乙机构的旧方案','published_at':None,'retrieved_at':1,'kind':'page','parent_url':None},
        {'id':'W02','title':'甲机构2026年接收工作方案','url':'https://example.org/target','host':'example.org','score':.8,
        'read_status':'read','content':'甲机构2026年接收工作方案：接收30人，申请人需满足文件列明的条件。'*100,'snippet':'甲机构接收30人','published_at':None,'retrieved_at':1,'kind':'page','parent_url':None}]
    return {'sources':sources,'selected_ids':['W02','W01'],'queries':[{'query':'甲机构接收工作方案'}],
        'tool_call':{'args':{'queries':['甲机构接收工作方案'],'purpose':'查找甲机构文件'}}}


class WebContextTests(unittest.TestCase):
    def runner(self):
        runner=object.__new__(WebSearchTool)
        runner.web=web_fixture()
        runner.settings=Settings()
        runner.question='查找甲机构接收文件'
        return runner

    def test_review_order_overrides_search_provider_score(self):
        runner=self.runner()
        self.assertEqual([s['id'] for s in runner.ranked(SimpleNamespace(preferred_domains=[]))],['W02','W01'])
        self.assertEqual([s['id'] for s in runner.evidence()],['W02','W01'])

    def test_stored_legacy_evidence_is_reordered_for_answer(self):
        web=web_fixture()
        runner=self.runner(); runner.web=web
        web['evidence']=list(reversed(runner.evidence()))
        service=SimpleNamespace(store=SimpleNamespace(get=lambda table,id:{'web':web}))
        context=CompanionService.web_context(service,'turn')
        self.assertEqual(context['sources'][0]['id'],'W02')
        self.assertEqual(context['source_inventory'][0]['id'],'W02')

    def test_repair_budget_keeps_primary_source_and_inventory(self):
        runner=self.runner()
        web=runner.web
        service=SimpleNamespace(store=SimpleNamespace(get=lambda table,id:{'web':dict(web,evidence=runner.evidence())}))
        context={'message':'查找甲机构接收文件','profile':{},'stage':{},'recent':[{'user':'旧消息'*1400,'assistant':'旧建议'*1400}],
            'summary':'旧摘要'*1500,'evidence':[], 'web':CompanionService.web_context(service,'turn')}
        original=copy.deepcopy(context)
        payload,report=fit_web_context(context,INSTRUCTION+WEB_RESPONSE_INSTRUCTION,CompanionReply.model_json_schema(),7500)
        self.assertEqual(payload['web']['sources'][0]['id'],'W02')
        self.assertTrue(payload['web']['sources'][0]['excerpt'])
        self.assertEqual({s['id'] for s in payload['web']['source_inventory']},{'W01','W02'})
        self.assertEqual(report['primary_source_id'],'W02')
        self.assertLessEqual(report['estimated_input_tokens'],5700)
        self.assertEqual(context,original,'context fitting must not mutate persisted evidence')

    def test_budget_too_small_stops_instead_of_substituting_a_weaker_source(self):
        context={'message':'查找当前文件','web':{'sources':[{'id':'W02','title':'甲机构','excerpt':'相关依据'*500}],
            'source_inventory':[{'id':'W02','title':'甲机构','read_status':'read'}]}}
        with self.assertRaises(ProviderError):
            fit_web_context(context,INSTRUCTION+WEB_RESPONSE_INSTRUCTION,CompanionReply.model_json_schema(),1000)

    def test_document_year_in_title_is_supported_but_invented_counts_are_not(self):
        self.assertTrue(citation_numbers_supported('2026年该机构接收30人','接收人数：30人。','甲机构2026年工作方案'))
        self.assertFalse(citation_numbers_supported('该机构接收3人','接收人数：30人。','甲机构2026年工作方案'))
        self.assertFalse(citation_numbers_supported('2049年该机构接收30人','接收人数：30人。','甲机构2026年工作方案'))

    def test_publication_year_does_not_override_requested_period(self):
        source={'title':'北港中心2030年度实施方案','published_at':'2031-11-01','snippet':''}
        for kind, conflict in [('publication_time',False),('effective_time',True)]:
            args=WebSearchArgs(queries=['北港中心方案'],purpose='查找文件',constraints=[
                SearchConstraint(kind=kind,quote='2031')])
            self.assertEqual(relevance(source,'2031年的文件',args)['different_period'],conflict)
        source['title']='2030年发布的实施方案'
        self.assertFalse(relevance(source,'2031年的文件',args)['different_period'])
        source['title']='2030年至2035年度实施方案'
        self.assertFalse(relevance(source,'2031年的文件',args)['different_period'])

    def test_citation_recovers_literal_spacing_but_never_splices_sections(self):
        passage='申请要求为 30 学分。\n…\n材料需要单独提交。'
        self.assertEqual(original_quote('申请要求为30学分。',passage),'申请要求为 30 学分。')
        self.assertIsNone(original_quote('要求为 30 学分。材料需要单独提交。',passage))

    def test_new_request_overrides_background_and_unquoted_conditions_are_dropped(self):
        explicit=SearchConstraint(kind='audience',quote='学徒')
        stale=SearchConstraint(kind='audience',quote='职工',origin='background')
        invented=SearchConstraint(kind='effective_time',quote='2032')
        self.assertEqual(grounded_constraints([stale,explicit,invented],'找学徒培训资料','职工'),[explicit])

    def test_deep_table_preserves_heading_and_requested_row_as_literal_quotes(self):
        header='| 项目 | 要求 |'
        row='| 定向培训补贴 | 需要培训证明 |'
        page='[主页](index)\n'*600+header+'\n| --- | --- |\n'+'| 其他 | 普通类 |\n'*80+row+'\n'
        passage=excerpt(page,['定向培训补贴'],350)
        self.assertIn(header,passage)
        self.assertIn(row,passage)
        self.assertLessEqual(len(passage),350)
        self.assertTrue(all(block in page for block in passage.split('\n…\n')))


if __name__=='__main__': unittest.main()
