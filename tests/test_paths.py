import asyncio
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from fastapi.testclient import TestClient
from backend.app import create_app

from backend.config import ROOT, Settings
from backend.path_models import PathResponse, PathSelection, PlanRevision, ProgressUpdate, StageRequest
from backend.path_store import PathConflict, PathStore
from backend.paths import PathService, PathWorkflow, source_context
from backend.store import Store


QUESTION = "虚构测试人物：生物专业研一，有Python基础和Agent项目，保持在读，准备开发实习"


def basis():
    return {"kind": "synthesis", "explanation": "结合用户已有项目与在读约束规划", "evidence_ids": [], "validation_action": ""}


class PathModel:
    def __init__(self, clarify=False, bad_citation=False):
        self.clarify = clarify
        self.bad_citation = bad_citation
        self.calls = []
        self.suggestions = []

    async def generate(self, schema, instruction, payload, max_tokens):
        self.calls.append(schema.__name__)
        await asyncio.sleep(0.001)
        if schema.__name__ == "PlanningReview":
            data = {"issues": [], "suggestions": self.suggestions}
        elif schema.__name__ == "CandidateProposal":
            if self.clarify and not payload["clarified"]:
                data = {"questions": [{"id": "time", "question": "每周可投入多少时间？", "reason": "安排投入强度"}], "paths": []}
            else:
                data = {"questions": [], "paths": [{
                    "title": name, "goal": goal, "approach": "保持在读，通过项目完善与反馈逐步准备实习",
                    "suitable_conditions": ["有基础项目并兼顾科研"], "first_action": "检查现有项目的失败场景",
                    "effort": "每周安排一次小迭代，按实际时间调整", "difficulties": ["工程基础需要补齐"],
                    "basis": {**basis(), **({"kind": "case", "evidence_ids": ["invented"]} if self.bad_citation else {})},
                } for name, goal in [("在读准备Agent实习", "Agent应用开发实习"), ("生物领域AI应用", "科研工具应用开发"), ("后端工程能力积累", "后端开发实习")]]}
        elif schema.__name__ == "PlanOutline":
            previous = payload.get("previous_plan")
            stages = copy.deepcopy(previous["stages"]) if previous else [{
                "id": "s" + str(index), "title": name, "objective": "结合现有项目完成" + name,
                "completion_criteria": "保存可复现的产出、日志与复盘记录", "depends_on": [] if index == 1 else ["s" + str(index - 1)],
                "effort_hours_min": 3, "effort_hours_max": 6, "already_completed": False, "user_evidence": [], "basis": basis(),
            } for index, name in enumerate(["完善现有项目", "验证项目质量", "准备投递材料", "实践与复盘"], 1)]
            if payload.get("adjustment", {}).get("instruction"):
                stages[-1]["objective"] = "降低投入强度，先做一次小范围反馈"
            data = {"title": "在读项目与实习探索", "goal": "通过已有项目准备实习", "stages": stages, "limitations": ["时间为规划估计，结果需实际验证"]}
        elif schema.__name__ == "StageDetails":
            data = {"tasks": [{
                "id": "t" + str(index), "title": name, "kind": "experiment", "description": "选定一个场景并执行一次可复现实验",
                "output": "一份实验日志和结果对比", "completion_criteria": "同一输入下可复现预期输出并记录实际结果",
                "depends_on": [] if index == 1 else ["t1"], "effort_hours": 1,
                "skills": ["问题定位", "项目表达"], "help_hint": "先缩小输入，再比较预期与实际结果", "basis": basis(),
            } for index, name in enumerate(["复现一个失败场景", "修复并记录实验结果"], 1)]}
        else:
            raise AssertionError(schema.__name__)
        return json.dumps(data, ensure_ascii=False), {"total_tokens": 150, "input_tokens": 100, "output_tokens": 50}


class PathTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        (ROOT / ".data").mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / ".data", prefix="paths-test-")
        self.settings = Settings(data_dir=Path(self.directory.name))
        self.retrieval = Store(self.settings.data_dir / "test.db")
        source = self.retrieval.create(QUESTION, self.settings)
        self.retrieval.change(source["id"], {"status": "finished", "profile": {
            "major": {"value": "生物", "source_text": "生物专业"}, "education": {"value": "研究生", "source_text": "研一"},
            "target": {"value": "Agent开发实习", "source_text": "准备开发实习"}, "constraints": [{"value": "保持在读", "source_text": "保持在读"}],
            "completed_actions": [{"value": "已有Agent项目", "source_text": "有Python基础和Agent项目"}],
        }})
        self.source_id = source["id"]
        self.store = PathStore(self.retrieval)
        self.model = PathModel()
        self.saver_context = AsyncSqliteSaver.from_conn_string(str(self.settings.data_dir / "checkpoints.db"))
        self.saver = await self.saver_context.__aenter__()
        await self.saver.setup()
        self.workflow = PathWorkflow(self.store, self.model, self.saver)
        self.service = PathService(self.settings, self.store, self.workflow)

    async def asyncTearDown(self):
        await self.service.close()
        await self.saver_context.__aexit__(None, None, None)
        self.directory.cleanup()

    async def wait_for(self, run_id, statuses):
        for _ in range(1000):
            run = self.store.snapshot(run_id)
            if run["status"] in statuses:
                return run
            await asyncio.sleep(0.01)
        self.fail("Path operation did not finish")

    async def create(self):
        run = await self.service.create(self.retrieval.snapshot(self.source_id))
        return await self.wait_for(run["id"], ("awaiting_selection", "awaiting_clarification", "failed"))

    async def selected(self):
        run = await self.create()
        self.assertEqual(run["status"], "awaiting_selection", run["error"])
        body = PathResponse(input_id=run["input_request"]["id"], candidate_id="c1")
        await self.service.respond(run["id"], body)
        return await self.wait_for(run["id"], ("ready", "failed"))

    async def test_end_to_end_selection_expansion_and_return_link(self):
        run = await self.selected()
        self.assertEqual(run["status"], "ready", run["error"])
        self.assertEqual(run["retrieval_run_id"], self.source_id)
        self.assertEqual(run["version"], 1)
        self.assertEqual(len(run["plan"]["stages"]), 4)
        first = run["plan"]["stages"][0]
        self.assertEqual(len(first["tasks"]), 2)
        self.assertEqual(run["plan"]["stages"][1]["tasks"], [])
        with self.assertRaises(PathConflict):
            self.store.update_progress(run["id"], ProgressUpdate(stage_id=first["id"], task_id="t2", version=1, status="completed"))
        for task in first["tasks"]:
            self.store.update_progress(run["id"], ProgressUpdate(stage_id=first["id"], task_id=task["id"], version=1, status="completed"))
        await self.service.advance(run["id"], StageRequest(stage_id=first["id"], version=1))
        advanced = await self.wait_for(run["id"], ("ready", "failed"))
        self.assertEqual(advanced["version"], 2, advanced["error"])
        self.assertEqual(advanced["current_stage_id"], advanced["plan"]["stages"][1]["id"])
        self.assertEqual(len(advanced["completed_work"]), 2)
        self.assertEqual(self.retrieval.get(self.source_id)["status"], "finished")
        self.assertEqual(len(self.store.version(run["id"], 1)["stages"][1]["tasks"]), 0)

    async def test_duplicate_creation_and_response_are_idempotent(self):
        run = await self.create()
        again = await self.service.create(self.retrieval.snapshot(self.source_id))
        self.assertEqual(run["id"], again["id"])
        response = PathResponse(input_id=run["input_request"]["id"], candidate_id="c1")
        await self.service.respond(run["id"], response)
        await self.service.respond(run["id"], response)
        ready = await self.wait_for(run["id"], ("ready", "failed"))
        await self.service.respond(run["id"], response)
        self.assertEqual(self.store.get(run["id"])["version"], 1, ready["error"])

    async def test_clarification_survives_restart_and_pauses_clock(self):
        self.model.clarify = True
        run = await self.create()
        self.assertEqual(run["status"], "awaiting_clarification")
        before = run["operation"]["elapsed_seconds"]
        await asyncio.sleep(0.03)
        self.assertAlmostEqual(self.store.snapshot(run["id"])["operation"]["elapsed_seconds"], before, delta=0.01)
        await self.service.close()
        self.service = PathService(self.settings, self.store, self.workflow)
        await self.service.recover()
        await self.service.respond(run["id"], PathResponse(input_id=run["input_request"]["id"], answers={"time": "每周10小时"}))
        ready = await self.wait_for(run["id"], ("awaiting_selection", "failed"))
        self.assertEqual(ready["status"], "awaiting_selection", ready["error"])
        self.assertEqual(ready["answers"], {"time": "每周10小时"})

    async def test_revision_requires_review_and_preserves_completed_tasks(self):
        run = await self.selected()
        first = run["plan"]["stages"][0]
        self.store.update_progress(run["id"], ProgressUpdate(stage_id=first["id"], task_id="t1", version=1, status="completed", note="已保存复现日志"))
        await self.service.revise(run["id"], PlanRevision(instruction="每周时间减少，请降低后续阶段强度", version=1))
        proposed = await self.wait_for(run["id"], ("awaiting_revision", "failed", "ready"))
        self.assertEqual(proposed["status"], "awaiting_revision", proposed["error"])
        self.assertEqual(proposed["version"], 1)
        await self.service.respond(run["id"], PathResponse(input_id=proposed["input_request"]["id"], approve=True))
        approved = await self.wait_for(run["id"], ("ready", "failed"))
        self.assertEqual(approved["version"], 2, approved["error"])
        self.assertEqual(approved["progress"][first["id"] + ":t1"]["status"], "completed")
        self.assertEqual(len(approved["plan"]["stages"][0]["tasks"]), 2)
        with self.assertRaises(PathConflict):
            self.store.update_progress(run["id"], ProgressUpdate(stage_id=first["id"], task_id="t2", version=1, status="completed"))

    async def test_rejected_revision_keeps_current_version(self):
        run = await self.selected()
        await self.service.revise(run["id"], PlanRevision(instruction="希望放慢接下来的探索节奏", version=1))
        proposed = await self.wait_for(run["id"], ("awaiting_revision", "ready", "failed"))
        await self.service.respond(run["id"], PathResponse(input_id=proposed["input_request"]["id"], approve=False))
        kept = await self.wait_for(run["id"], ("ready", "failed"))
        self.assertEqual(kept["version"], 1)
        self.assertIsNone(kept["pending_revision"])

    async def test_empty_cases_allow_synthesis_and_invalid_citations_are_rejected(self):
        run = await self.create()
        self.assertEqual(len(run["candidates"]), 3)
        self.assertTrue(all(item["basis"]["kind"] == "synthesis" for item in run["candidates"]))
        self.assertEqual(run["evidence_catalog"], {})

    async def test_fabricated_evidence_cannot_be_saved(self):
        self.model.bad_citation = True
        run = await self.create()
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["candidates"], [])
        self.assertIn("证据", run["error"])

    async def test_budget_stop_is_separate_from_retrieval(self):
        self.service.settings = Settings(data_dir=self.settings.data_dir, path_candidate_tokens=100)
        run = await self.create()
        self.assertEqual(run["stop_reason"], "token_budget")
        self.assertEqual(self.retrieval.get(self.source_id)["limits"]["tokens"], 100000)

    async def test_same_operation_commit_is_idempotent(self):
        run = await self.selected()
        self.store.commit_plan(run["id"], run["plan"], "恢复时重复提交")
        self.assertEqual(self.store.get(run["id"])["version"], 1)

    async def test_pause_and_new_direction_preserve_completed_history(self):
        run = await self.selected()
        first = run["plan"]["stages"][0]
        body = ProgressUpdate(stage_id=first["id"], task_id="t1", version=1, status="completed")
        self.store.change(run["id"], {"journey_status": "paused"})
        with self.assertRaises(PathConflict):
            self.store.update_progress(run["id"], body)
        self.store.change(run["id"], {"journey_status": "active"})
        self.store.update_progress(run["id"], body)
        self.store.change(run["id"], {"journey_status": "completed"})
        await self.service.select(run["id"], PathSelection(candidate_id="c2", version=1))
        selected = await self.wait_for(run["id"], ("ready", "failed"))
        self.assertEqual(selected["journey_status"], "active")
        self.assertNotEqual(selected["plan"]["stages"][0]["id"], first["id"])
        self.assertEqual(len(selected["completed_work"]), 1)
        self.assertRegex(selected["current_stage_id"], r"^[a-z]")

    async def test_optional_suggestions_do_not_block_planning(self):
        self.model.suggestions = ["后续可增加作品说明细节"]
        run = await self.selected()
        self.assertEqual(run["status"], "ready", run["error"])
        self.assertTrue(any(e["event_type"] == "validation.suggestions" for e in self.store.events(run["id"])))

    async def test_restart_after_new_operation_saved_before_dispatch(self):
        run = await self.selected()
        await self.service.await_checkpoint(run["id"])
        self.service.begin(run["id"], "revise", {"instruction": "每周时间减少，请放慢后续阶段"})
        await self.service.close()
        self.service = PathService(self.settings, self.store, self.workflow)
        await self.service.recover()
        restored = await self.wait_for(run["id"], ("awaiting_revision", "ready", "failed"))
        self.assertEqual(restored["status"], "awaiting_revision", restored["error"])
        self.assertEqual(restored["version"], 1)

    async def test_source_index_preserves_quotes_and_bounds_model_context(self):
        source = self.retrieval.snapshot(self.source_id)
        quote = "虚构案例的连续原文证据" * 40
        source["cases"] = [{"id": f"case{i}", "title": "虚构案例", "facts": {
            field: {"value": "案例信息" * 50, "quote": quote, "hit_id": f"hit{i}"}
            for field in ["major", "education", "target", "plans", "actions", "stage_outcomes"]},
            "source": {"url": "https://www.zhihu.com/question/1/answer/2", "title": "虚构测试来源"}}
            for i in range(8)]
        catalog, cases = source_context(source)
        run, _ = self.store.create(source, catalog, cases)
        context = self.workflow.context(run)
        self.assertEqual(catalog["case0:major"]["quote"], quote)
        self.assertLess(len(context["evidence"]), len(catalog))
        self.assertTrue(all(len(e["quote"]) <= 260 for e in context["evidence"]))
        self.assertEqual(context["evidence"][0]["id"], "case0:major")


class PathApiTests(unittest.TestCase):
    def test_http_contracts_and_progress_survive_reopening(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".data", prefix="paths-api-") as folder:
            settings = Settings(data_dir=Path(folder))
            application = create_app(settings, model=PathModel())
            with TestClient(application) as client:
                store = application.state.store
                source = store.create(QUESTION, settings)
                source_id = source["id"]
                self.assertIsNone(client.get(f"/api/runs/{source_id}/paths").json())
                self.assertEqual(client.post(f"/api/runs/{source_id}/paths").status_code, 409)
                store.change(source_id, {"status": "finished", "profile": {"target": {"value": "Agent实习"}}})
                response = client.post(f"/api/runs/{source_id}/paths")
                self.assertEqual(response.status_code, 202)
                path_id = response.json()["id"]

                def wait_for(status):
                    for _ in range(500):
                        value = client.get(f"/api/paths/{path_id}").json()
                        if value["status"] == status:
                            return value
                        time.sleep(0.01)
                    self.fail("API operation did not reach " + status)

                choice = wait_for("awaiting_selection")
                self.assertEqual(client.post(f"/api/runs/{source_id}/paths").json()["id"], path_id)
                self.assertEqual(client.post(f"/api/paths/{path_id}/respond", json={"input_id": "stale", "candidate_id": "c1"}).status_code, 409)
                self.assertEqual(client.post(f"/api/paths/{path_id}/respond", json={"input_id": choice["input_request"]["id"], "candidate_id": "c1"}).status_code, 202)
                ready = wait_for("ready")
                stage = ready["plan"]["stages"][0]
                progress = {"version": 1, "stage_id": stage["id"], "task_id": "t1", "status": "completed", "note": "虚构测试：保存实验记录"}
                self.assertEqual(client.patch(f"/api/paths/{path_id}/progress", json={**progress, "version": 9}).status_code, 409)
                self.assertEqual(client.patch(f"/api/paths/{path_id}/progress", json=progress).status_code, 200)
                self.assertEqual(client.get(f"/api/paths/{path_id}/versions/1").status_code, 200)
                self.assertEqual(client.get(f"/api/paths/{path_id}/versions/99").status_code, 404)
                self.assertEqual(client.get("/api/paths/missing").status_code, 404)
                events = application.state.path_store.events(path_id)
                self.assertEqual([item["sequence"] for item in events], list(range(1, len(events) + 1)))
                self.assertTrue(all(item["agent"] == "path_planner" for item in events))
            with TestClient(create_app(settings, model=PathModel())) as client:
                restored = client.get(f"/api/runs/{source_id}/paths").json()
                self.assertEqual(restored["progress"][stage["id"] + ":t1"]["status"], "completed")
                self.assertEqual(restored["status"], "ready")
                self.assertEqual(client.get(f"/api/runs/{source_id}").json()["status"], "finished")


if __name__ == "__main__":
    unittest.main()
