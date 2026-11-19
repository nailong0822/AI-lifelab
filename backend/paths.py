"""带持久化人工选择、证据校验和计划版本的人生路径工作流。"""

import asyncio
import copy
import hashlib
import json
import re
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError

from .path_models import CandidateProposal, PlanOutline, PlanningReview, StageDetails
from .path_store import PathConflict, PathStore
from .providers import ProviderError, clean_text, estimate_tokens
from .ranking import rank_key
from .store import uid
from .workflow import BudgetReached


class PathState(TypedDict, total=False):
    run_id: str
    operation: str
    operation_id: str
    needs_clarification: bool
    answer: dict
    approve: bool


def elapsed(operation):
    return operation["active_seconds"] + (max(0, time.time() - operation["clock_started_at"])
                                          if operation.get("clock_started_at") else 0)


def source_context(source):
    catalog = {}
    cases = []
    for case in sorted(source["cases"], key=rank_key)[:8]:
        facts = {}
        for field, fact in case["facts"].items():
            evidence_id = case["id"] + ":" + field
            catalog[evidence_id] = {"id": evidence_id, "case_id": case["id"], "field": field,
                                    "value": fact["value"], "quote": fact["quote"],
                                    "source": case["source"], "hit_id": fact["hit_id"]}
            facts[field] = {"value": fact["value"], "evidence_id": evidence_id}
        cases.append({"id": case["id"], "title": case["title"], "facts": facts, "source":case["source"],
                      "matching": {key: (case.get("matching") or {}).get(key) for key in ("score", "tier")},
                      "differences": case.get("background_differences", [])})
    return catalog, cases


class PathWorkflow:
    def __init__(self, store: PathStore, model, saver):
        self.store = store
        self.model = model
        graph = StateGraph(PathState)
        for name, handler in {
            "candidates": self.candidates, "clarify": self.clarify, "merge": self.merge,
            "choose": self.choose, "plan": self.plan, "review_revision": self.review_revision,
            "save": self.save_plan, "expand": self.expand,
        }.items():
            graph.add_node(name, handler)
        graph.add_conditional_edges(START, lambda state: {
            "candidates": "candidates", "plan": "plan", "revise": "plan", "expand": "expand",
        }[state["operation"]])
        graph.add_conditional_edges("candidates", lambda state: "clarify" if state.get("needs_clarification") else "choose")
        graph.add_edge("clarify", "merge")
        graph.add_edge("merge", "candidates")
        graph.add_edge("choose", "plan")
        graph.add_conditional_edges("plan", lambda state: "review_revision" if self.store.get(state["run_id"])["operation"]["kind"] == "revise" else "save")
        graph.add_edge("review_revision", "save")
        graph.add_edge("save", END)
        graph.add_edge("expand", END)
        self.graph = graph.compile(checkpointer=saver)

    def context(self, run):
        # Keep full quotes in the source index; send a bounded, diverse evidence
        # selection to the model so long retrieval results cannot consume a run.
        catalog = run["evidence_catalog"]
        field_order = ["major", "education", "actions", "plans", "stage_outcomes", "target",
                       "constraints", "starting_point", "person_context", "time_and_cost", "year", "career_stage", "event_time"]
        evidence = []
        used = 0
        for field in field_order:
            for case in run["source_cases"]:
                item = catalog.get(case["id"] + ":" + field)
                if not item:
                    continue
                excerpt = {"id": item["id"], "value": item["value"][:120], "quote": item["quote"][:260]}
                cost = estimate_tokens(json.dumps(excerpt, ensure_ascii=False))
                if used + cost <= 4500:
                    evidence.append(excerpt)
                    used += cost
        selected_ids = {item["id"] for item in evidence}
        cases = [{"id": case["id"], "title": case["title"], "matching": case["matching"],
                  "differences": case["differences"], "evidence_ids": [fact["evidence_id"] for fact in case["facts"].values()
                                                                          if fact["evidence_id"] in selected_ids]}
                 for case in run["source_cases"]]
        return {
            "question": run["question"], "profile": run["profile"],
            "retrieval_answers": (run.get("retrieval_clarification") or {}).get("answers"),
            "planning_answers": run["answers"], "cases": cases, "evidence": evidence,
            "retrieval_gaps": run["source_gaps"], "completed_work": self.completed_context(run["id"]),
            "task_feedback": [{"task": value.get("task_title"), "status": value["status"], "note": value.get("note", "")[:400]}
                              for value in run["progress"].values()][-10:],
        }

    def completed_context(self, run_id):
        return [{**item, "note": item["note"][:300]} for item in self.store.completed_work(run_id)[:12]]

    def user_text(self, run):
        payload = (run.get('operation') or {}).get('payload', {})
        return "\n".join([run["question"], payload.get('trusted_user_text', payload.get('instruction', '')), *run["answers"].values(),
                          *((run.get("retrieval_clarification") or {}).get("answers") or {}).values(),
                          *["已完成：" + item["title"] for item in self.store.completed_work(run["id"])]] )

    async def call(self, run_id, key, schema, instruction, payload, output_limit=3500):
        run = self.store.get(run_id)
        operation = run["operation"]
        call_key = operation["id"] + ":" + key
        cached = run["model_calls"].get(call_key)
        if cached and cached.get("status") == "completed":
            return schema.model_validate(cached["response"])
        for attempt in range(2):
            run = self.store.get(run_id)
            operation = run["operation"]
            if elapsed(operation) >= operation["limits"]["seconds"]:
                raise BudgetReached("time_budget")
            estimate = estimate_tokens(instruction + json.dumps(payload, ensure_ascii=False)
                                       + json.dumps(schema.model_json_schema(), ensure_ascii=False)) + 200
            available = operation["limits"]["tokens"] - operation["tokens_used"] - estimate
            if available < 300:
                raise BudgetReached("token_budget")
            maximum = min(output_limit, available)
            reservation = estimate + maximum
            def reserve(current, db):
                current["operation"]["tokens_used"] += reservation
                current["model_calls"][call_key] = {"status": "running", "reservation": reservation,
                                                     "operation_id": operation["id"]}
            self.store.mutate(run_id, reserve, event_type="node.started", node=key,
                              title="正在校验规划" if ":review:" in key else {
                                  "candidates": "正在生成候选航线", "outline": "正在规划阶段与星球",
                                  "details": "正在细化当前阶段任务"}.get(key.split(":")[0], "正在校验规划"))
            try:
                content, usage = await asyncio.wait_for(
                    self.model.generate(schema, instruction, payload, maximum),
                    timeout=max(0.1, min(45, operation["limits"]["seconds"] - elapsed(operation))),
                )
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError as error:
                raise BudgetReached("time_budget") from error
            except Exception as error:
                raise ProviderError("路径模型调用失败，请检查服务配置与网络后重试") from error
            usage = usage or {}
            actual = usage.get("total_tokens")
            if actual is None and usage.get("input_tokens") is not None:
                actual = usage["input_tokens"] + usage.get("output_tokens", 0)
            estimated = actual is None
            actual = estimate + estimate_tokens(str(content)) if estimated else int(actual)
            def settle(current, db):
                current["operation"]["tokens_used"] += actual - reservation
                current["operation"]["estimated_usage"] |= estimated
                current["model_calls"][call_key] = {"status": "returned", "operation_id": operation["id"],
                                                     "tokens": actual, "estimated": estimated}
            self.store.mutate(run_id, settle, event_type="budget.updated", node=key,
                              title="规划模型用量已更新", payload={"tokens": actual, "estimated": estimated,
                                  "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")})
            try:
                result = schema.model_validate_json(content, extra="ignore")
            except (ValidationError, ValueError, TypeError) as error:
                errors = [{"field": ".".join(map(str, item["loc"])), "message": item["msg"]}
                          for item in error.errors(include_input=False, include_url=False)[:8]] if isinstance(error, ValidationError) else []
                instruction += "\n请修复这些结构错误后输出完整JSON：" + json.dumps(errors, ensure_ascii=False)
                self.store.emit(run_id, "node.repair", "正在修复规划输出结构", {"errors": errors}, node=key)
                continue
            def complete(current, db):
                current["model_calls"][call_key].update(status="completed", response=result.model_dump())
            self.store.mutate(run_id, complete, event_type="node.completed", node=key, title="规划节点已完成")
            return result
        raise ProviderError("路径模型输出未通过结构校验，可以保留当前进度后重试")

    def basis_issues(self, value, catalog):
        issues = []
        if isinstance(value, dict):
            if "basis" in value:
                basis = value["basis"]
                if any(item not in catalog for item in basis["evidence_ids"]):
                    issues.append("引用了不存在的evidence_id，请仅使用输入中的证据ID")
                if basis["kind"] == "case" and not basis["evidence_ids"]:
                    issues.append("案例支持必须关联至少一条真实证据")
                if basis["kind"] == "hypothesis" and not basis["validation_action"].strip():
                    issues.append("待验证假设需要写明验证行动")
            for item in value.values():
                issues.extend(self.basis_issues(item, catalog))
        elif isinstance(value, list):
            for item in value:
                issues.extend(self.basis_issues(item, catalog))
        return list(dict.fromkeys(issues))

    def structure_issues(self, schema, body, run):
        issues = self.basis_issues(body, run["evidence_catalog"])
        if schema is CandidateProposal:
            if len(body["paths"]) < 3:
                issues.append("生成3至4条有实际差异的候选路径")
            titles = [clean_text(path["title"]) for path in body["paths"]]
            if len(set(titles)) != len(titles):
                issues.append("候选路径标题重复，需要有实际差异")
        if schema in (PlanOutline, StageDetails):
            entries = body["stages"] if schema is PlanOutline else body["tasks"]
            seen = set()
            for entry in entries:
                if entry["id"] in seen or any(item not in seen for item in entry["depends_on"]):
                    issues.append("ID必须唯一，前置依赖必须位于当前步骤之前，不能出现循环")
                seen.add(entry["id"])
                if schema is PlanOutline and entry["already_completed"]:
                    if not entry["user_evidence"] or any(not item.strip() or clean_text(item) not in clean_text(self.user_text(run)) for item in entry["user_evidence"]):
                        issues.append("已完成阶段需要用户原话依据，不能从他人案例推断用户已完成")
        text = json.dumps(body, ensure_ascii=False)
        if re.search(r"(?:保证|必然|一定能|确保).{0,12}(?:拿到.*(?:offer|实习|录用)|找到.*工作|成功转行)", text, re.I):
            issues.append("移除对录用、实习或转行结果的保证，用可执行行动和待达成里程碑表达")
        return issues

    async def validated(self, run_id, key, schema, instruction, payload):
        for attempt in range(2):
            run = self.store.get(run_id)
            result = await self.call(run_id, key + f":{attempt}", schema, instruction, payload, output_limit=4500)
            body = result.model_dump()
            if schema is CandidateProposal and result.questions and not run["clarified"]:
                return result
            issues = self.structure_issues(schema, body, run)
            review = await self.call(
                run_id, key + f":review:{attempt}", PlanningReview,
                "审核人生路径规划。issues仅列阻断性错误，最多3条，每条必须指出明确的用户硬约束与相反的方案原文，"
                "或被伪造的案例引用/结果保证，或明显属于其他阶段的任务（附当前阶段目标和冲突任务原文）。没有明确错误时issues必须为空。正面评价绝不能放入issues。"
                "其余表达、细节、排序、可行性不确定等改进仅放suggestions，不阻断。"
                "按proposal_type审核：CandidateProposal只是选方向的初步候选，不要求完整任务、依赖、README或验收标准；"
                "不同应用场景、学习方式或验证方式可以作为不同路线，不因都需要项目而认定重复。"
                "PlanOutline才要求阶段顺序与完成标准；StageDetails才要求具体任务与产出。"
                "允许案例为空，synthesis是常规建议而非事实，不需要引文；hypothesis只需说明验证行动。"
                "用户缺乏某技能正是学习路径要解决的问题，不能因此否决。资源可用性标为待核实即可。"
                "禁止编造人物、薪资、成功率或保证录用。用户后来明确选择或补充的信息优先；保留完成记录。",
                {"user": {"question": run["question"], "profile": run["profile"], "answers": run["answers"],
                          "retrieval_answers": (run.get("retrieval_clarification") or {}).get("answers"),
                          "selection": run["selection"], "adjustment": run["operation"].get("payload")},
                 "proposal_type": schema.__name__, "proposal": body, "target_stage": payload.get("stage"),
                 "plan_scope": payload.get("plan"), "evidence": payload.get("context", {}).get("evidence", []),
                 "completed_work": self.completed_context(run_id)}, output_limit=1200,
            )
            issues.extend(review.issues)
            if review.suggestions:
                self.store.emit(run_id, "validation.suggestions", "规划校验完成，保留可选改进建议",
                                {"suggestions": review.suggestions}, node=key)
            if not issues:
                return result
            self.store.emit(run_id, "validation.repair", "规划需要调整，正在修复", {"issues": issues}, node=key)
            instruction += "\n修复这些问题后输出完整结果：" + json.dumps(issues, ensure_ascii=False)
        raise ProviderError("规划仍有约束或证据问题，请查看轨迹后调整要求或重试")

    def input_request(self, run_id, kind, data):
        current = self.store.get(run_id)["input_request"]
        if current and current["kind"] == kind:
            return current
        request = {"id": uid(), "kind": kind, "data": data}
        self.store.change(run_id, {"input_request": request}, event_type="input.required",
                          title={"clarification": "需要确认规划条件", "selection": "请为自己选择一条航线",
                                 "revision": "计划调整已准备好，请审阅"}[kind], payload=request)
        return request

    async def candidates(self, state):
        run = self.store.get(state["run_id"])
        result = await self.validated(
            run["id"], "candidates:clarified" if run["clarified"] else "candidates", CandidateProposal,
            "根据用户目标、已有能力、约束与检索结果，生成3至4条可比较的人生路径。"
            "每条同时说明目标和实现方式，给出第一步、投入估计、困难和依据。"
            "案例不足仍可规划，用synthesis或hypothesis说明。禁止虚构成功案例或保证结果。"
            "已经具备Python基础或项目经验时，从适合当前起点的行动开始。遵循保持在读等明确约束。"
            "仅当缺少会改变路径选择的关键信息时，一次集中提出最多3个questions，此时paths可为空。"
            "clarified=true时questions必须为空，未知条件写入适用条件，仍给出可尝试路径。"
            "basis使用给定evidence_ids；假设填写validation_action。输出简洁。",
            {"context": self.context(run), "clarified": run["clarified"]},
        )
        if result.questions and not run["clarified"]:
            self.input_request(run["id"], "clarification", {"questions": [item.model_dump() for item in result.questions]})
            return {"needs_clarification": True}
        paths = [{"id": f"c{index + 1}", **path.model_dump()} for index, path in enumerate(result.paths)]
        self.store.change(run["id"], {"candidates": paths, "input_request": None},
                          event_type="candidates.ready", title="候选航线已生成并校验", payload={"count": len(paths)})
        return {"needs_clarification": False}

    async def clarify(self, state):
        answer = interrupt(self.store.get(state["run_id"])["input_request"])
        return {"answer": answer}

    async def merge(self, state):
        self.store.change(state["run_id"], {"answers": state["answer"]["answers"], "clarified": True,
                                           "input_request": None})
        return {}

    async def choose(self, state):
        run = self.store.get(state["run_id"])
        request = self.input_request(run["id"], "selection", {"candidates": run["candidates"]})
        answer = interrupt(request)
        return {"answer": answer}

    def normalize(self, outline, run):
        plan = outline.model_dump()
        route_id = run["selection"]["route_id"]
        ids = {}
        for stage in plan["stages"]:
            identifier = stage["id"] if stage["id"].startswith(route_id + "-") else route_id + "-" + stage["id"]
            if len(identifier) > 61:
                identifier = identifier[:50] + "-" + hashlib.sha256(identifier.encode()).hexdigest()[:10]
            ids[stage["id"]] = identifier
        old = {stage["id"]: stage for stage in (run.get("plan") or {}).get("stages", [])}
        for stage in plan["stages"]:
            stage["id"] = ids[stage["id"]]
            stage["depends_on"] = [ids[item] for item in stage["depends_on"]]
            previous = old.get(stage["id"])
            if previous and (stage["title"], stage["objective"]) == (previous["title"], previous["objective"]):
                stage["tasks"] = previous.get("tasks", [])
            else:
                if previous and any(run["progress"].get(stage["id"] + ":" + task["id"], {}).get("status") == "completed" for task in previous.get("tasks", [])):
                    raise ProviderError("调整改变了含已完成任务的阶段，请保留该阶段的名称与目标后重新调整")
                stage["tasks"] = []
        plan["route_id"] = route_id
        plan["candidate_id"] = run["selection"].get("candidate_id")
        return plan

    async def plan(self, state):
        run = self.store.get(state["run_id"])
        candidate = next((item for item in run["candidates"] if item["id"] == run["selection"].get("candidate_id")), None)
        previous = copy.deepcopy(run["plan"]) if (run.get("plan") or {}).get("route_id") == run["selection"]["route_id"] else None
        if previous:
            for stage in previous["stages"]:
                stage.pop("tasks", None)
        outline = await self.validated(
            run["id"], "outline", PlanOutline,
            "为用户选定的方向生成4至6个阶段的路径概览。阶段对应星球，名称清楚，说明目标、完成标准与预计投入小时范围。"
            "阶段必须有顺序，depends_on仅引用之前的阶段ID。ID使用小写英文标识。"
            "把可执行行动与求职等结果里程碑区分，结果不得承诺，允许未知时间。"
            "复用已完成能力；already_completed只能根据user_text中的用户原话或已完成任务记录判断，并填写连续原文user_evidence。"
            "调整已有计划时，保留包含已完成任务的阶段ID、名称和目标，修改后续阶段。"
            "若用户要求修改尚无完成任务的当前阶段任务，需要同步更新该阶段objective以体现新范围并触发任务重新细化。"
            "投入小时是规划估计，不能伪装为来源事实。basis标明案例支持、综合建议或待验证假设。",
            {"context": self.context(run), "selection": run["selection"], "candidate": candidate,
             "previous_plan": previous, "adjustment": run["operation"].get("payload"), "user_text": self.user_text(run)},
        )
        plan = self.normalize(outline, run)
        first = next((stage for stage in plan["stages"] if not stage["already_completed"]), plan["stages"][-1])
        if run["operation"]["kind"] == "revise":
            first = next((stage for stage in plan["stages"] if stage["id"] == run["current_stage_id"]), first)
        if not first["tasks"]:
            first["tasks"] = await self.details(run, plan, first)
        self.store.change(run["id"], {"pending_revision": plan}, event_type="plan.proposed",
                          title="阶段计划与当前任务已准备好", payload={"stages": len(plan["stages"]), "current_tasks": len(first["tasks"])})
        return {"approve": True}

    async def details(self, run, plan, stage):
        result = await self.validated(
            run["id"], "details:" + stage["id"], StageDetails,
            "细化指定阶段，生成2至4个明确任务。每个任务说明行动、产出、完成标准、预计投入小时、技能与遇到困难时的帮助提示。"
            "kind使用action/experiment/milestone，milestone表示需用户实际反馈的结果。"
            "任务ID为小写英文，依赖只引用本阶段先前任务。skills最多四个简短能力词。"
            "任务执行者是用户本人，用直接行动措辞；写‘记录你实际运行的结果’，不要写‘给用户看’或‘交给用户’，不暗示Agent已经替用户执行。"
            "严格限定在指定stage的目标与完成标准内，不能提前安排其他星球的任务；特别是项目中间阶段不应安排投递、录用或整条路线的最终复盘。"
            "避免重复已完成工作，结合现实投入时间，把过大任务拆小。引用只用给定证据ID。",
            {"context": self.context(run), "plan": {"title": plan["title"], "goal": plan["goal"],
                 "stages": [{"title": item["title"], "objective": item["objective"]} for item in plan["stages"]]}, "stage": stage},
        )
        return [task.model_dump() for task in result.tasks]

    async def review_revision(self, state):
        request = self.input_request(state["run_id"], "revision", {"version": self.store.get(state["run_id"])["version"]})
        answer = interrupt(request)
        return {"approve": answer["approve"]}

    async def save_plan(self, state):
        run = self.store.get(state["run_id"])
        if state.get("approve", True):
            if not run["pending_revision"] and (run.get("plan") or {}).get("operation_id") == run["operation"]["id"]:
                return {}
            self.store.commit_plan(run["id"], run["pending_revision"],
                                   "根据反馈调整计划" if run["operation"]["kind"] == "revise" else "用户选择了探索方向")
        else:
            self.store.change(run["id"], {"pending_revision": None, "input_request": None, "status": "ready"},
                              event_type="revision.dismissed", title="已继续使用当前计划")
        return {}

    async def expand(self, state):
        run = self.store.get(state["run_id"])
        plan = copy.deepcopy(run["plan"])
        stage = next(stage for stage in plan["stages"] if stage["id"] == run["operation"]["payload"]["stage_id"])
        if not stage["tasks"]:
            stage["tasks"] = await self.details(run, plan, stage)
            self.store.commit_plan(run["id"], plan, "展开阶段任务：" + stage["title"])
        else:
            self.store.change(run["id"], {"status": "ready"})
        return {}


class PathService:
    def __init__(self, settings, store, workflow):
        self.settings = settings
        self.store = store
        self.workflow = workflow
        self.tasks = {}
        self.lock = asyncio.Lock()
        self.shutting_down = False

    def begin(self, run_id, kind, payload=None, changes=None):
        limits = {
            "candidates": (self.settings.path_candidate_tokens, 60),
            "plan": (self.settings.path_plan_tokens, 90),
            "revise": (self.settings.path_revision_tokens, 60),
            "expand": (self.settings.path_candidate_tokens, 60),
        }
        tokens, seconds = limits[kind]
        def start(run, db):
            previous = run.get("operation")
            if previous:
                previous["clock_started_at"] = None
                run["operation_history"].append(previous)
            run.update(changes or {})
            run.update(status="running", error=None, stop_reason=None)
            run["operation"] = {"id": uid(), "kind": kind, "payload": payload or {}, "tokens_used": 0,
                                "active_seconds": 0.0, "clock_started_at": time.time(), "estimated_usage": False,
                                "limits": {"tokens": tokens, "seconds": seconds}, "status": "running"}
        self.store.mutate(run_id, start, event_type="operation.started", title="开始路径规划", payload={"kind": kind, "tokens": tokens})

    def schedule(self, run_id, value):
        if isinstance(value, dict):
            value = {**value, "operation_id": self.store.get(run_id)["operation"]["id"]}
        self.tasks[run_id] = asyncio.create_task(self.execute(run_id, value))

    async def await_checkpoint(self, run_id):
        # A node can publish ready/waiting before LangGraph flushes its checkpoint.
        # Only join that final flush; do not queue a new action behind active work.
        task = self.tasks.get(run_id)
        if task and self.store.get(run_id)["status"] != "running":
            await asyncio.shield(task)

    async def create(self, source):
        async with self.lock:
            if source["status"] not in ("finished", "cancelled", "failed") or not source.get("profile"):
                raise PathConflict("请先完成检索与目标澄清，再开始规划路径")
            catalog, cases = source_context(source)
            run, created = self.store.create(source, catalog, cases)
            if created:
                self.begin(run["id"], "candidates")
                self.schedule(run["id"], {"run_id": run["id"], "operation": "candidates"})
        return self.store.snapshot(run["id"])

    async def execute(self, run_id, value):
        config = {"configurable": {"thread_id": "path:" + run_id}, "recursion_limit": 30}
        try:
            await self.workflow.graph.ainvoke(value, config=config)
            run = self.store.get(run_id)
            if run["input_request"]:
                kind = run["input_request"]["kind"]
                self.store.change(run_id, {"status": "awaiting_" + kind},
                                  event_type="operation.waiting", title="规划已保存，等待你的选择")
            self.stop_clock(run_id, "waiting" if run["input_request"] else "completed")
        except asyncio.CancelledError:
            self.stop_clock(run_id, "interrupted")
        except (BudgetReached, ProviderError) as error:
            reason = error.reason if isinstance(error, BudgetReached) else "service_error"
            message = {"token_budget": "本次规划剩余Token预算不足，可查看轨迹并重试", "time_budget": "本次规划时间预算已结束，可以重试"}.get(reason, str(error))
            self.fail(run_id, reason, message)
        except Exception:
            self.fail(run_id, "workflow_error", "路径规划执行异常，当前计划与进度已保存，可以重试")
        finally:
            self.tasks.pop(run_id, None)

    def stop_clock(self, run_id, status):
        def stop(run, db):
            run["operation"]["clock_started_at"] = None
            run["operation"]["status"] = status
            for call in run["model_calls"].values():
                if call["status"] == "running":
                    call.update(status="unknown", estimated=True)
                    run["operation"]["estimated_usage"] = True
        self.store.mutate(run_id, stop)

    def fail(self, run_id, reason, message):
        run = self.store.get(run_id)
        self.store.change(run_id, {"status": "ready" if run["plan"] else "failed", "error": message, "stop_reason": reason,
                                  "input_request": None}, event_type="operation.failed", title=message, payload={"reason": reason})
        self.stop_clock(run_id, "failed")

    def check_available(self, run, version):
        self.store.check_version(run, version)
        if run["status"] != "ready":
            raise PathConflict("请先完成当前规划操作或选择")

    def selection(self, run, candidate_id, custom_goal):
        if candidate_id and not any(item["id"] == candidate_id for item in run["candidates"]):
            raise PathConflict("候选航线不存在，请刷新后重试")
        if not candidate_id and len(custom_goal.strip()) < 5:
            raise PathConflict("请选择一条航线，或填写自己的探索方向")
        return {"candidate_id": candidate_id, "custom_goal": custom_goal.strip(), "route_id": "r" + uid()[:9]}

    async def respond(self, run_id, body):
        async with self.lock:
            await self.await_checkpoint(run_id)
            run = self.store.get(run_id)
            response = body.model_dump(exclude_none=True)
            old = run["submissions"].get(body.input_id)
            if old:
                if old == response:
                    return self.store.snapshot(run_id)
                raise PathConflict("这次选择已提交，请刷新页面")
            request = run["input_request"]
            if not request or request["id"] != body.input_id or not run["status"].startswith("awaiting_"):
                raise PathConflict("等待项已变化，请刷新页面")
            kind = request["kind"]
            if kind == "clarification":
                expected = {question["id"] for question in request["data"]["questions"]}
                if not body.answers or set(body.answers) != expected or any(not value.strip() or len(value) > 2000 for value in body.answers.values()):
                    raise PathConflict("请回答每个补充问题，也可以填写暂不确定")
                answer = {"answers": body.answers}
            elif kind == "selection":
                selection = self.selection(run, body.candidate_id, body.custom_goal)
                self.begin(run_id, "plan", changes={"selection": selection, "journey_status": "active"})
                answer = selection
            else:
                if body.approve is None:
                    raise PathConflict("请明确是否采用这次计划调整")
                answer = {"approve": body.approve}
            def submitted(current, db):
                current["submissions"][body.input_id] = response
                current["last_submission"] = {"kind": kind, "answer": answer}
                current["status"] = "running"
                current["operation"]["clock_started_at"] = time.time()
            self.store.mutate(run_id, submitted, event_type="input.received", title="已收到你的选择，继续规划")
            self.schedule(run_id, Command(resume=answer, update={"operation_id": self.store.get(run_id)["operation"]["id"]}))
        return self.store.snapshot(run_id)

    async def select(self, run_id, body):
        async with self.lock:
            await self.await_checkpoint(run_id)
            run = self.store.get(run_id)
            self.check_available(run, body.version)
            selection = self.selection(run, body.candidate_id, body.custom_goal)
            self.begin(run_id, "plan", changes={"selection": selection, "input_request": None, "journey_status": "active"})
            self.schedule(run_id, {"run_id": run_id, "operation": "plan"})
        return self.store.snapshot(run_id)

    async def revise(self, run_id, body, *, action_id=None, user_evidence=None):
        async with self.lock:
            await self.await_checkpoint(run_id)
            run = self.store.get(run_id)
            if action_id and any((op.get('payload') or {}).get('companion_action_id') == action_id
                                 for op in [*run['operation_history'], run.get('operation') or {}]):
                return self.store.snapshot(run_id)
            self.check_available(run, body.version)
            payload = {"instruction": body.instruction, 'companion_action_id': action_id}
            if user_evidence is not None:
                payload['trusted_user_text'] = '\n'.join(user_evidence)
            self.begin(run_id, "revise", payload, {"input_request": None})
            self.schedule(run_id, {"run_id": run_id, "operation": "revise"})
        return self.store.snapshot(run_id)

    async def expand(self, run_id, body):
        async with self.lock:
            await self.await_checkpoint(run_id)
            run = self.store.get(run_id)
            self.check_available(run, body.version)
            stage = next((item for item in run["plan"]["stages"] if item["id"] == body.stage_id), None)
            if not stage:
                raise PathConflict("阶段不存在")
            if stage["tasks"]:
                return self.store.snapshot(run_id)
            self.begin(run_id, "expand", {"stage_id": body.stage_id})
            self.schedule(run_id, {"run_id": run_id, "operation": "expand"})
        return self.store.snapshot(run_id)

    async def advance(self, run_id, body):
        async with self.lock:
            await self.await_checkpoint(run_id)
            run = self.store.get(run_id)
            self.check_available(run, body.version)
            stages = run["plan"]["stages"]
            if run["journey_status"] == "paused":
                raise PathConflict("请先继续这段探索")
            index = next((index for index, stage in enumerate(stages) if stage["id"] == body.stage_id), None)
            if index is None or body.stage_id != run["current_stage_id"]:
                raise PathConflict("当前停靠位置已变化，请刷新星图")
            stage = stages[index]
            if not stage["tasks"] or not all(run["progress"].get(stage["id"] + ":" + task["id"], {}).get("status") in ("completed", "skipped") for task in stage["tasks"]):
                raise PathConflict("请先完成或跳过当前阶段的任务")
            destination = next((item for item in stages[index + 1:] if not item["already_completed"]), None)
            if destination is None:
                self.store.change(run_id, {"journey_status": "completed"}, event_type="journey.completed", title="这段探索已完成，可以复盘或规划新的方向")
                return self.store.snapshot(run_id)
            self.store.change(run_id, {"current_stage_id": destination["id"]}, event_type="stage.advanced",
                              title="已前往下一颗星球", payload={"from": stage["id"], "to": destination["id"]})
            if not destination["tasks"]:
                self.begin(run_id, "expand", {"stage_id": destination["id"]})
                self.schedule(run_id, {"run_id": run_id, "operation": "expand"})
        return self.store.snapshot(run_id)

    async def retry(self, run_id):
        async with self.lock:
            await self.await_checkpoint(run_id)
            run = self.store.get(run_id)
            if run["status"] == "running" or not run["error"]:
                raise PathConflict("当前操作无需重试")
            previous = run["operation"]
            self.begin(run_id, previous["kind"], previous["payload"], {"input_request": None, "pending_revision": None})
            self.schedule(run_id, {"run_id": run_id, "operation": previous["kind"]})
        return self.store.snapshot(run_id)

    async def recover(self):
        for run in self.store.list_active():
            run_id = run["id"]
            if run["operation"] is None:
                self.begin(run_id, "candidates")
            else:
                self.stop_clock(run_id, "interrupted")
                self.store.mutate(run_id, lambda current, db: current["operation"].update(clock_started_at=time.time()))
            checkpoint = await self.workflow.graph.aget_state({"configurable": {"thread_id": "path:" + run_id}})
            operation = self.store.get(run_id)["operation"]
            same_operation = checkpoint.values.get("operation_id") == operation["id"]
            value = None if same_operation and checkpoint.next else {"run_id": run_id, "operation": operation["kind"]}
            submission = run.get("last_submission")
            waiting = {"clarify": "clarification", "choose": "selection", "review_revision": "revision"}
            if submission and any(waiting.get(node) == submission["kind"] for node in checkpoint.next):
                value = Command(resume=submission["answer"], update={"operation_id": operation["id"]})
            if "choose" in checkpoint.next and run["selection"] and self.store.get(run_id)["operation"]["kind"] == "plan":
                value = Command(resume=run["selection"], update={"operation_id": operation["id"]})
            self.store.emit(run_id, "operation.recovered", "正在恢复已保存的路径规划")
            self.schedule(run_id, value)

    async def close(self):
        self.shutting_down = True
        pending = list(self.tasks.values())
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
