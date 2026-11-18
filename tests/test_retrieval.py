import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from backend.app import create_app
from backend.config import ROOT, Settings
from backend.models import DimensionAssessment, Profile, ResumeInput
from backend.providers import ProviderError, ZhihuSearch, normalize_hits
from backend.service import RetrievalService
from backend.store import Store
from backend.ranking import analysis_stats, coverage_for, rank_key, relevant_excerpt, score_case, source_priority
from backend.workflow import RetrievalWorkflow

QUESTION = "我是生物专业研一学生，希望在读找AI Agent开发实习，每周10小时"
TEXT = "我是非计算机专业研究生，生物专业研一，目标是AI Agent实习，在读期间完成了一个项目，获得面试机会。"


def profile():
    return {
        "education": {"value": "研究生", "source_text": "研一"},
        "major": {"value": "生物", "source_text": "生物"},
        "target": {"value": "AI Agent", "source_text": "AI Agent"},
        "decision_question": "在读期间如何准备 AI Agent 实习",
    }


def draft(number):
    return {"terms": ["实习", "困难", str(number)], "purpose": "补查相近背景实习经历",
            "target_gap": "时间投入", "relaxed_fields": ["major"]}


class FakeModel:
    def __init__(self, clarify=False, blank=False):
        self.clarify = clarify
        self.blank = blank

    async def generate(self, schema, instruction, payload, max_tokens):
        await asyncio.sleep(0.002)
        if self.blank:
            self.blank = False
            return "", {"total_tokens": 30}
        if schema.__name__ == "Understanding":
            questions = []
            if self.clarify and "previous_profile" not in payload:
                questions = [{"id": "path", "question": "优先在读准备还是考虑休学？", "reason": "确认检索路径"}]
            result = {"profile": profile(), "questions": questions}
        elif schema.__name__ == "InitialPlan":
            result = {"queries": [draft(0), draft(1)]}
        elif schema.__name__ == "Extraction":
            result = {"cases": [{
                "source_hit_id": hit["source_hit_id"], "subject": "作者", "title": "在读准备实习的经历",
                "source_nature": "self_report",
                "person_context": {"value": "非计算机专业研究生", "quote": "非计算机专业研究生"},
                "major": {"value": "生物专业", "quote": "生物专业"},
                "education": {"value": "研究生", "quote": "研究生"},
                "target": {"value": "AI Agent实习", "quote": "目标是AI Agent实习"},
                "actions": {"value": "完成项目", "quote": "完成了一个项目"},
                "stage_outcomes": {"value": "获得面试机会", "quote": "获得面试机会"},
                "time_and_cost": {"value": "三个月", "quote": "这个引文在原文中不存在"},
                "applicability": "具体专业与投入时间仍有差异",
            } for hit in payload["sources"][:6]]}
        elif schema.__name__ == "EvidenceReview":
            result = {"judgments": [
                {"case_index": case["case_index"], "field": field,
                 "supported": not ("Offer" in fact["value"] and "面试" in fact["quote"])}
                for case in payload["cases"] for field, fact in case["facts"].items()
            ], "experiences": [
                {"case_index": case["case_index"], "actual_experience": True, "relevant": True,
                 "background_match": "partial", "differences": ["具体专业未知"]}
                for case in payload["cases"]
            ]}
            for experience in result["experiences"]:
                experience["assessments"] = [
                    {"dimension": field, "level": 1, "reason": "用户与引用中的信息一致", "evidence_fields": [field]}
                    for field in ("major", "education", "target")
                ]
        elif schema.__name__ == "GapAnalysis":
            result = {"sufficient": False, "explanation": "继续补查准备耗时",
                      "gaps": [{"dimension": "time_and_cost", "description": "准备耗时未知", "kind": "search"}],
                      "next_query": draft(len(payload["previous_queries"]) + 1)}
        else:
            raise AssertionError(schema.__name__)
        return json.dumps(result, ensure_ascii=False), {"total_tokens": 200}


class FakeSearch:
    def __init__(self, fail=False, delay=0):
        self.calls = 0
        self.fail = fail
        self.delay = delay
        self.counts = []

    async def search(self, query, count, timeout):
        self.calls += 1
        self.counts.append(count)
        number = self.calls
        await asyncio.sleep(self.delay)
        if self.fail:
            raise ProviderError("暂时限流", retryable=True)
        return {"search_hash": "fixture", "items": [{
            "ContentID": str(index), "ContentType": "answer", "Title": "测试经历", "ContentText": TEXT,
            "Url": f"https://www.zhihu.com/question/1/answer/{index}?utm_source=test", "AuthorName": "测试作者",
        } for index in range(number, number + count)]}


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        (ROOT / ".data").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="test-", dir=ROOT / ".data")
        self.settings = Settings(data_dir=Path(self.temp.name), token_budget=40_000)
        self.store = Store(self.settings.data_dir / "app.db")
        self.context = AsyncSqliteSaver.from_conn_string(str(self.settings.data_dir / "checkpoints.db"))
        self.saver = await self.context.__aenter__()
        await self.saver.setup()
        self.search = FakeSearch()
        self.model = FakeModel()
        self.workflow = RetrievalWorkflow(self.store, self.model, self.search, self.saver)
        self.service = RetrievalService(self.settings, self.store, self.workflow)

    async def asyncTearDown(self):
        await self.service.close()
        await self.context.__aexit__(None, None, None)
        self.temp.cleanup()

    async def wait_for(self, run_id, statuses=("finished", "failed", "cancelled")):
        for _ in range(800):
            run = self.store.snapshot(run_id)
            if run["status"] in statuses:
                return run
            await asyncio.sleep(0.01)
        self.fail("Task did not reach expected state")

    async def test_full_graph_request_cap_and_evidence(self):
        result = await self.wait_for(self.service.create(QUESTION)["id"])
        self.assertEqual(result["status"], "finished", result["error"])
        self.assertEqual(self.search.calls, 4)
        self.assertEqual(result["request_count"], 4)
        self.assertEqual(self.search.counts, [10, 6, 5, 5])
        self.assertEqual(result["queries"][0]["relaxed_fields"], [])
        self.assertEqual(result["queries"][1]["relaxed_fields"], [])
        self.assertEqual(result["stop_reason"], "request_limit")
        self.assertGreater(len(result["cases"]), 0)
        self.assertLess(len({h["source_id"] for h in result["hits"]}), len(result["hits"]))
        for case in result["cases"]:
            self.assertNotIn("time_and_cost", case["facts"])
            for fact in case["facts"].values():
                hit = next(hit for hit in result["hits"] if hit["id"] == fact["hit_id"])
                self.assertIn(fact["quote"], hit["text"])
        events = self.store.events(result["id"])
        self.assertEqual([e["sequence"] for e in events], list(range(1, len(events) + 1)))

    async def test_coverage_complete_skips_q03_and_q04(self):
        original = self.model.generate
        async def sufficient(schema, instruction, payload, max_tokens):
            if schema.__name__ == "GapAnalysis":
                return json.dumps({"sufficient": True, "explanation": "用户关心的维度已有多来源支持",
                                   "gaps": [], "next_query": None}), {"total_tokens": 200}
            return await original(schema, instruction, payload, max_tokens)
        self.model.generate = sufficient
        result = await self.wait_for(self.service.create(QUESTION)["id"])
        self.assertEqual(result["stop_reason"], "coverage_met", result["error"])
        self.assertEqual(self.search.counts, [10, 6])
        self.assertEqual(result["result_status"], "complete")
        self.assertTrue(all(row["status"] == "clear" for row in result["coverage"]))

    async def test_false_sufficient_with_missing_professional_evidence_continues_search(self):
        original = self.model.generate
        async def optimistic(schema, instruction, payload, max_tokens):
            content, usage = await original(schema, instruction, payload, max_tokens)
            body = json.loads(content)
            if schema.__name__ == "Extraction":
                for case in body["cases"]:
                    case.pop("major", None)
            if schema.__name__ == "GapAnalysis":
                body["sufficient"] = True
                body["gaps"] = []
            return json.dumps(body), usage
        self.model.generate = optimistic
        result = await self.wait_for(self.service.create(QUESTION)["id"])
        self.assertEqual(self.search.calls, 4)
        self.assertEqual(next(row for row in result["coverage"] if row["dimension"] == "major")["status"], "missing")

    async def test_more_than_six_sources_are_analyzed_and_statistics_are_distinct(self):
        result = await self.wait_for(self.service.create(QUESTION)["id"])
        stats = result["report"]["stats"]
        self.assertGreater(stats["analyzed_sources"], 6)
        self.assertEqual(stats["sources"], stats["analyzed_sources"] + stats["pending_sources"])
        self.assertEqual(stats["cited_sources"], len({case["source_id"] for case in result["cases"]}))
        self.assertEqual(stats["cases"], len(result["cases"]))
        self.assertGreater(stats["hits"], stats["sources"])

    async def test_retry_keeps_original_query_quota(self):
        self.search.fail = True
        result = await self.wait_for(self.service.create(QUESTION)["id"])
        self.assertEqual(result["request_count"], 4)
        self.assertCountEqual(self.search.counts, [10, 6, 10, 6])

    async def test_clarification_resume_and_duplicate_submit(self):
        self.model.clarify = True
        run_id = self.service.create(QUESTION)["id"]
        paused = await self.wait_for(run_id, ("awaiting_input", "failed"))
        self.assertEqual(paused["status"], "awaiting_input", paused["error"])
        await asyncio.sleep(0.05)
        self.assertAlmostEqual(self.store.snapshot(run_id)["elapsed_seconds"], paused["elapsed_seconds"], delta=0.02)
        answer = ResumeInput(clarification_id=paused["clarification"]["id"], answers={"path": "在读找实习"})
        await self.service.resume(run_id, answer)
        await self.service.resume(run_id, answer)
        result = await self.wait_for(run_id)
        self.assertEqual(result["status"], "finished", result["error"])
        self.assertEqual(result["profile_version"], 2)
        self.assertEqual(self.search.calls, 4)

    async def test_retries_share_the_four_request_budget(self):
        self.search.fail = True
        result = await self.wait_for(self.service.create(QUESTION)["id"])
        self.assertEqual(self.search.calls, 4)
        self.assertEqual(result["request_count"], 4)
        self.assertTrue(all(q["status"] == "failed" for q in result["queries"]))

    async def test_token_budget_can_stop_before_search(self):
        self.service.settings = Settings(data_dir=self.settings.data_dir, token_budget=100)
        result = await self.wait_for(self.service.create(QUESTION)["id"])
        self.assertEqual(result["stop_reason"], "token_budget")
        self.assertEqual(self.search.calls, 0)
        self.assertIsNotNone(result["report"])

    async def test_insufficient_remaining_search_tokens_reports_budget_stop(self):
        run = self.store.create(QUESTION, self.settings)
        self.store.change(run["id"], {"tokens_used": self.settings.token_budget - 1000})
        state = {"run_id": run["id"]}
        self.assertEqual(self.workflow.after_extraction(state), "finalize")
        await self.workflow.finalize(state)
        self.assertEqual(self.store.snapshot(run["id"])["stop_reason"], "token_budget")

    async def test_cancel_before_worker_starts(self):
        run_id = self.service.create(QUESTION)["id"]
        result = await self.service.cancel(run_id)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.search.calls, 0)

    async def test_interrupted_model_usage_is_marked_as_estimated(self):
        async def slow(schema, instruction, payload, max_tokens):
            await asyncio.sleep(5)
            return "{}", {"total_tokens": 1}
        self.model.generate = slow
        run_id = self.service.create(QUESTION)["id"]
        while not self.store.get(run_id)["model_calls"]:
            await asyncio.sleep(0.01)
        result = await self.service.cancel(run_id)
        self.assertTrue(result["tokens_estimated"])
        self.assertGreater(result["tokens_used"], 0)

    async def test_restart_after_clarification_submit_recovers_answer(self):
        self.model.clarify = True
        run_id = self.service.create(QUESTION)["id"]
        paused = await self.wait_for(run_id, ("awaiting_input", "failed"))
        self.assertEqual(paused["status"], "awaiting_input")
        clarification = paused["clarification"]
        clarification["submitted_answers"] = {"path": "在读准备"}
        self.store.change(run_id, {"status": "running", "clarification": clarification})
        await self.service.close()
        self.service = RetrievalService(self.settings, self.store, self.workflow)
        await self.service.recover()
        result = await self.wait_for(run_id)
        self.assertEqual(result["status"], "finished", result["error"])
        self.assertEqual(result["profile_version"], 2)

    async def test_query_guard_rejects_undergraduate_for_graduate(self):
        from backend.models import QueryDraft
        run = self.store.create(QUESTION, self.settings)
        self.store.change(run["id"], {"profile": profile(), "profile_version": 1})
        invalid = QueryDraft(**{**draft(0), "terms": ["本科", "转行"]})
        self.assertEqual(self.workflow.validate_queries(self.store.get(run["id"]), [invalid]), [])

    async def test_semantic_review_rejects_offer_claim_supported_only_by_interview(self):
        original = self.model.generate
        async def altered(schema, instruction, payload, max_tokens):
            content, usage = await original(schema, instruction, payload, max_tokens)
            if schema.__name__ == "Extraction":
                body = json.loads(content)
                for case in body["cases"]:
                    case["stage_outcomes"]["value"] = "获得 Offer"
                content = json.dumps(body, ensure_ascii=False)
            return content, usage
        self.model.generate = altered
        result = await self.wait_for(self.service.create(QUESTION)["id"])
        self.assertGreater(len(result["cases"]), 0)
        self.assertTrue(all("stage_outcomes" not in case["facts"] for case in result["cases"]))

    async def test_new_quote_for_existing_case_is_preserved(self):
        import copy
        result = await self.wait_for(self.service.create(QUESTION)["id"])
        candidate = copy.deepcopy(result["cases"][0])
        candidate["facts"]["actions"]["quote"] = "在读期间完成了一个项目"
        candidate["facts"]["actions"]["value"] = "在读期间完成项目"
        self.store.save_cases(result["id"], [candidate])
        saved = next(case for case in self.store.get(result["id"])["cases"] if case["id"] == candidate["id"])
        self.assertEqual(saved["facts"]["actions"]["quote"], "在读期间完成了一个项目")
        self.assertEqual(saved["additional_evidence"][0]["quote"], result["cases"][0]["facts"]["actions"]["quote"])
        with self.store.connection() as db:
            rows = db.execute("SELECT data FROM evidence WHERE case_id=?", (candidate["id"],)).fetchall()
        self.assertTrue(any("在读期间完成了一个项目" in row[0] for row in rows))

    async def test_advice_without_observed_action_is_not_an_experience(self):
        original = self.model.generate
        async def advice_only(schema, instruction, payload, max_tokens):
            content, usage = await original(schema, instruction, payload, max_tokens)
            if schema.__name__ == "EvidenceReview":
                body = json.loads(content)
                for item in body["experiences"]:
                    item["actual_experience"] = False
                content = json.dumps(body)
            return content, usage
        self.model.generate = advice_only
        result = await self.wait_for(self.service.create(QUESTION)["id"])
        self.assertEqual(result["cases"], [])
        self.assertEqual(result["result_status"], "empty")
        self.assertGreater(len(result["hits"]), 0)

    async def test_time_budget_can_stop_before_search(self):
        self.service.settings = Settings(data_dir=self.settings.data_dir, active_seconds=1)
        result = await self.wait_for(self.service.create(QUESTION)["id"])
        self.assertEqual(result["stop_reason"], "time_budget")
        self.assertEqual(self.search.calls, 0)

    async def test_cancellation_keeps_partial_report(self):
        self.search.delay = 3
        run_id = self.service.create(QUESTION)["id"]
        while self.search.calls < 1:
            await asyncio.sleep(0.01)
        result = await self.service.cancel(run_id)
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNotNone(result["report"])

    async def test_recovery_keeps_inflight_requests_counted(self):
        self.search.delay = 3
        run_id = self.service.create(QUESTION)["id"]
        while self.search.calls < 2:
            await asyncio.sleep(0.01)
        await self.service.close()
        self.search.delay = 0
        self.service = RetrievalService(self.settings, self.store, self.workflow)
        await self.service.recover()
        result = await self.wait_for(run_id)
        self.assertEqual(sum(q["status"] == "unknown" for q in result["queries"]), 2)
        self.assertLessEqual(result["request_count"], 4)
        self.assertEqual(self.search.calls, 4)

    async def test_blank_json_output_is_repaired(self):
        self.model.blank = True
        result = await self.wait_for(self.service.create(QUESTION)["id"])
        self.assertEqual(result["status"], "finished", result["error"])
        self.assertEqual(result["tokens_used"] % 200, 30)

    async def test_extra_model_notes_keep_valid_cases_and_scores(self):
        original = self.model.generate
        async def notes(schema, instruction, payload, max_tokens):
            content, usage = await original(schema, instruction, payload, max_tokens)
            body = json.loads(content)
            body["profile_note"] = "补充说明"
            if schema.__name__ == "Extraction":
                for case in body["cases"]:
                    case["debug_note"] = "补充说明"
            return json.dumps(body), usage
        self.model.generate = notes
        result = await self.wait_for(self.service.create(QUESTION)["id"])
        self.assertIsNone(result["error"])
        self.assertGreater(len(result["cases"]), 0)
        self.assertTrue(all(case["matching"]["score"] > 0 for case in result["cases"]))


class ApiTests(unittest.TestCase):
    def test_api_history_and_sse_replay(self):
        (ROOT / ".data").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="api-test-", dir=ROOT / ".data") as directory:
            settings = Settings(data_dir=Path(directory), token_budget=40_000)
            with TestClient(create_app(settings, model=FakeModel(), search=FakeSearch())) as client:
                response = client.post("/api/runs", json={"question": QUESTION})
                self.assertEqual(response.status_code, 202)
                run_id = response.json()["id"]
                for _ in range(500):
                    result = client.get("/api/runs/" + run_id).json()
                    if result["status"] != "running":
                        break
                    time.sleep(0.01)
                self.assertEqual(result["status"], "finished", result["error"])
                self.assertNotIn("model_calls", result)
                self.assertEqual(client.get("/api/runs").json()[0]["id"], run_id)
                self.assertEqual(client.get(f"/api/runs/{run_id}/report").status_code, 200)
                events = client.get(f"/api/runs/{run_id}/events").text
                self.assertIn("event: trace", events)
                self.assertIn("event: settled", events)
                tail = client.get(f"/api/runs/{run_id}/events",
                                  headers={"Last-Event-ID": str(result["last_event_sequence"])}).text
                self.assertNotIn("event: trace", tail)
                self.assertEqual(client.get("/api/runs/missing").status_code, 404)
                def legacy(current, db):
                    current.pop("workflow_version", None)
                    for case in current["cases"]:
                        case.pop("matching", None)
                client.app.state.store.mutate(run_id, legacy)
                old = client.get("/api/runs/" + run_id).json()
                self.assertEqual(old["status"], "finished")
                self.assertIsNone(old["analysis_stats"])
                self.assertTrue(all("matching" not in case for case in old["cases"]))


class RankingTests(unittest.TestCase):
    def test_unrelated_scoring_references_are_ignored(self):
        assessment = DimensionAssessment.model_validate({"dimension": "major", "level": 1,
            "reason": "模型引用了不适用字段", "evidence_fields": ["stage_outcomes", "unknown_field"]})
        result = score_case({"facts": {"stage_outcomes": {"value": "获得面试"}}}, profile(), [assessment.model_dump()])
        major = next(item for item in result["dimensions"] if item["dimension"] == "major")
        self.assertIsNone(major["level"])
        self.assertEqual(major["contribution"], 0)

    def test_clarification_with_invalid_quote_retains_verified_target(self):
        updated = {**profile(), "target": {"value": "模型重新拼接的目标", "source_text": "原文中不存在的拼接引用"}}
        result = RetrievalWorkflow.validate_profile(Profile.model_validate(updated), QUESTION, previous=profile())
        self.assertEqual(result["target"], profile()["target"])

    def test_unknown_case_fields_keep_the_same_weight_denominator(self):
        user = profile()
        case = {"id": "a", "facts": {"major": {"value": "生物"}}}
        assessments = [{"dimension": "major", "level": 1, "reason": "专业相同", "evidence_fields": ["major"]},
                       {"dimension": "education", "level": 1, "reason": "缺少引用的判断", "evidence_fields": ["education"]}]
        result = score_case(case, user, assessments)
        self.assertAlmostEqual(result["score"], 35.7, places=1)
        self.assertAlmostEqual(result["field_coverage"], 35.7, places=1)
        self.assertIsNone(next(item for item in result["dimensions"] if item["dimension"] == "education")["level"])
        self.assertAlmostEqual(sum(item["weight"] for item in result["dimensions"]), 100, places=3)

    def test_background_tier_precedes_weighted_score(self):
        close = {"id": "close", "matching": {"tier": 1, "score": 70, "field_coverage": 85}}
        distant = {"id": "distant", "matching": {"tier": 3, "score": 95, "field_coverage": 100}}
        self.assertEqual(sorted([distant, close], key=rank_key)[0]["id"], "close")

    def test_background_after_character_1000_is_preserved(self):
        hit = {"source": {"title": "准备经历"}, "text": "一般建议。" * 500 + TEXT}
        excerpt = relevant_excerpt(hit, profile())
        self.assertIn("生物专业研一", excerpt)
        self.assertLessEqual(len(excerpt), 1800)
        self.assertGreater(source_priority({"source": {"title": ""}, "text": TEXT}, profile()),
                           source_priority({"source": {"title": ""}, "text": "机械专业本科实习"}, profile()))

    def test_repeated_hits_count_as_one_analyzed_source(self):
        hits = [{"id": "first", "source_id": "source", "text": TEXT},
                {"id": "again", "source_id": "source", "text": TEXT}]
        stats = analysis_stats({"hits": hits, "cases": [], "analyses": {"first": {"status": "completed", "candidate_ids": []}}})
        self.assertEqual((stats["hits"], stats["sources"], stats["analyzed_sources"], stats["pending_sources"]), (2, 1, 1, 0))


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_headers_and_response(self):
        def handler(request):
            self.assertEqual(request.headers["authorization"], "Bearer fixture-secret")
            self.assertTrue(request.headers["x-request-timestamp"].isdigit())
            self.assertEqual(request.url.params["Count"], "5")
            return httpx.Response(200, json={"Code": 0, "Data": {"Items": [], "SearchHashId": "test"}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await ZhihuSearch("fixture-secret", client).search("研究生 实习", 5, 10)
            self.assertEqual(result["items"], [])

    async def test_source_identity_and_original_links(self):
        base = {"ContentType": "Answer", "ContentID": "1", "ContentText": "<em>研究生</em>的经历"}
        items = [{**base, "Url": "https://www.zhihu.com/answer/1?utm_source=first"},
                 {**base, "Url": "https://www.zhihu.com/answer/1?utm_source=second"}]
        hits = normalize_hits("run", "query", items)
        self.assertEqual(hits[0]["source_id"], hits[1]["source_id"])
        self.assertEqual(hits[0]["text"], "研究生的经历")
        self.assertIn("utm_source=first", hits[0]["source"]["url"])


if __name__ == "__main__":
    unittest.main()
