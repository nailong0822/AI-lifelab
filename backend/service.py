"""任务运行器与浏览器连接独立，使用持久化图状态恢复任务。"""

import asyncio
import time

from langgraph.types import Command

from .config import Settings
from .models import ResumeInput
from .providers import ProviderError
from .store import Store
from .workflow import BudgetReached, RetrievalWorkflow


class RunConflict(Exception):
    pass


class RetrievalService:
    def __init__(self, settings: Settings, store: Store, workflow: RetrievalWorkflow):
        self.settings = settings
        self.store = store
        self.workflow = workflow
        self.tasks: dict[str, asyncio.Task] = {}
        self.shutting_down = False
        self.resume_lock = asyncio.Lock()

    def schedule(self, run_id: str, value, event: str):
        task = asyncio.create_task(self.execute(run_id, value, event))
        self.tasks[run_id] = task

    def create(self, question: str) -> dict:
        run = self.store.create(question.strip(), self.settings)
        self.schedule(run["id"], {"run_id": run["id"]}, "run.started")
        return self.store.snapshot(run["id"])

    async def execute(self, run_id: str, value, event: str):
        self.store.change(run_id, {"status": "running", "clock_started_at": time.time()},
                          event_type=event, node="run",
                          title="开始检索" if event == "run.started" else "继续检索")
        config = {"configurable": {"thread_id": run_id}, "recursion_limit": 40}
        try:
            result = await self.workflow.graph.ainvoke(value, config=config)
            if result and result.get("__interrupt__"):
                run = self.store.get(run_id)
                self.store.change(run_id, {"status": "awaiting_input", "clock_started_at": None},
                                  event_type="clarification.required", node="clarify",
                                  title="需要你补充一些信息",
                                  payload={"clarification": run["clarification"]})
            elif self.store.get(run_id)["status"] == "running":
                await self.workflow.finalize({"run_id": run_id})
        except BudgetReached as error:
            await self.workflow.finalize({"run_id": run_id, "stop_reason": error.reason})
        except ProviderError as error:
            self.store.change(run_id, {"error": str(error)})
            self.store.emit(run_id, "node.failed", "service", str(error))
            await self.workflow.finalize({"run_id": run_id, "stop_reason": "service_error"})
        except asyncio.CancelledError:
            if self.shutting_down:
                self.store.change(run_id, {"clock_started_at": None}, event_type="run.interrupted",
                                  node="service", title="服务关闭，执行状态已保存")
            else:
                await self.workflow.finalize({"run_id": run_id, "stop_reason": "cancelled"})
        except Exception:
            self.store.change(run_id, {"error": "工作流执行异常，已保存当前结果，请查看轨迹或重新发起任务"})
            await self.workflow.finalize({"run_id": run_id, "stop_reason": "service_error"})
        finally:
            self.tasks.pop(run_id, None)

    async def resume(self, run_id: str, answer: ResumeInput) -> dict:
        async with self.resume_lock:
            run = self.store.get(run_id)
            clarification = run.get("clarification")
            if not clarification or clarification["id"] != answer.clarification_id:
                raise RunConflict("澄清项已变化，请刷新任务")
            if clarification.get("submitted_answers") is not None:
                if clarification["submitted_answers"] == answer.answers:
                    return self.store.snapshot(run_id)
                raise RunConflict("这次澄清已提交")
            if run["status"] != "awaiting_input":
                raise RunConflict("当前任务没有等待补充")
            expected = {question["id"] for question in clarification["questions"]}
            if set(answer.answers) != expected or any(
                not value.strip() or len(value) > 2000 for value in answer.answers.values()
            ):
                raise RunConflict("请填写每个补充问题，也可以回答暂不确定")
            clarification["submitted_answers"] = answer.answers
            self.store.change(run_id, {"clarification": clarification, "status": "running"})
            self.schedule(run_id, Command(resume={"answers": answer.answers}), "run.resumed")
        return self.store.snapshot(run_id)

    async def cancel(self, run_id: str) -> dict:
        run = self.store.get(run_id)
        if run["status"] in ("finished", "failed", "cancelled"):
            return self.store.snapshot(run_id)
        task = self.tasks.get(run_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self.store.get(run_id)["status"] not in ("finished", "failed", "cancelled"):
            await self.workflow.finalize({"run_id": run_id, "stop_reason": "cancelled"})
        return self.store.snapshot(run_id)

    async def recover(self):
        for item in self.store.list():
            if item["status"] != "running":
                continue
            run_id = item["id"]
            self.store.recover(run_id)
            state = await self.workflow.graph.aget_state({"configurable": {"thread_id": run_id}})
            value = None if state.values else {"run_id": run_id}
            clarification = self.store.get(run_id).get("clarification")
            if clarification and clarification.get("submitted_answers") and "clarify" in state.next:
                value = Command(resume={"answers": clarification["submitted_answers"]})
            self.schedule(run_id, value, "run.recovered")

    async def close(self):
        self.shutting_down = True
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
