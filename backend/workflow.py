"""具备预算、人工澄清和可追溯证据的 LangGraph 工作流。"""

import asyncio
import hashlib
import json
import time
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from .models import EvidenceReview, Extraction, GapAnalysis, InitialPlan, Profile, QueryDraft, Understanding
from .providers import ProviderError, clean_text, estimate_tokens, normalize_hits
from .ranking import (FACT_LABELS, analysis_stats, comparison_profile, coverage_for,
                      rank_key, relevant_excerpt, score_case, source_priority)
from .store import Store, active_elapsed as elapsed


class GraphState(TypedDict, total=False):
    run_id: str
    needs_clarification: bool
    clarification_answer: dict
    pending_queries: list[dict]
    batch_hit_ids: list[str]
    no_gain_batches: int
    stop_reason: str


class BudgetReached(Exception):
    def __init__(self, reason: str):
        self.reason = reason


class RetrievalWorkflow:
    def __init__(self, store: Store, model, search, checkpointer):
        self.store = store
        self.model = model
        self.search = search
        builder = StateGraph(GraphState)
        for name, handler in {
            "understand": self.understand, "clarify": self.clarify,
            "merge_answers": self.merge_answers, "plan_initial": self.plan_initial,
            "search": self.execute_search, "extract": self.extract,
            "analyze": self.analyze, "finalize": self.finalize,
        }.items():
            builder.add_node(name, handler)
        builder.add_edge(START, "understand")
        builder.add_conditional_edges("understand", lambda state: "clarify" if state.get("needs_clarification") else "plan_initial")
        builder.add_edge("clarify", "merge_answers")
        builder.add_edge("merge_answers", "plan_initial")
        builder.add_edge("plan_initial", "search")
        builder.add_edge("search", "extract")
        builder.add_conditional_edges("extract", self.after_extraction)
        builder.add_conditional_edges("analyze", lambda state: "finalize" if state.get("stop_reason") else "search")
        builder.add_edge("finalize", END)
        self.graph = builder.compile(checkpointer=checkpointer)

    def budget_check(self, run: dict, *, searching=False):
        if elapsed(run) >= run["limits"]["seconds"] - run["limits"]["reserve_seconds"]:
            raise BudgetReached("time_budget")
        if run["tokens_used"] >= run["limits"]["tokens"]:
            raise BudgetReached("token_budget")
        if searching and run["request_count"] >= run["limits"]["requests"]:
            raise BudgetReached("request_limit")
        if searching and run["limits"]["tokens"] - run["tokens_used"] < 2000:
            raise BudgetReached("token_budget")

    async def call_model(self, run_id: str, key: str, schema, instruction: str, payload: dict, *, token_reserve=0):
        run = self.store.get(run_id)
        cached = run["model_calls"].get(key)
        if cached and cached.get("status") == "completed":
            try:
                return schema.model_validate(cached["response"])
            except ValidationError:
                self.store.emit(run_id, "node.updated", key.split(":")[0], "分析结构已更新，正在重新校验")
        for attempt in range(2):
            started_at = time.monotonic()
            run = self.store.get(run_id)
            self.budget_check(run)
            estimate = estimate_tokens(instruction + json.dumps(payload, ensure_ascii=False)
                                       + json.dumps(schema.model_json_schema(), ensure_ascii=False)) + 300
            available = run["limits"]["tokens"] - run["tokens_used"] - estimate - token_reserve
            if available < 256:
                raise BudgetReached("token_budget")
            output_limit = min(4096, available)
            reservation = estimate + output_limit
            def reserve(current, db):
                current["tokens_used"] += reservation
                current["tokens_estimated"] = True
                current["model_calls"][key] = {"status": "running", "reserved_tokens": reservation}
            self.store.mutate(run_id, reserve, event_type="node.started", node=key.split(":")[0],
                              title={"understand": "正在理解问题", "plan": "正在规划查询",
                                     "merge": "正在合并补充信息", "extract": "正在提取经历与证据",
                                     "analyze": "正在评估证据缺口", "verify": "正在核对字段与来源语义"}.get(key.split(":")[0], "正在处理"),
                              span_id=key + f":{attempt}")
            timeout = max(0.1, min(45, run["limits"]["seconds"] - elapsed(run) - run["limits"]["reserve_seconds"]))
            try:
                content, usage = await asyncio.wait_for(
                    self.model.generate(schema, instruction, payload, output_limit), timeout=timeout,
                )
            except asyncio.TimeoutError as error:
                if elapsed(self.store.get(run_id)) >= run["limits"]["seconds"] - run["limits"]["reserve_seconds"]:
                    raise BudgetReached("time_budget") from error
                raise ProviderError("模型响应超时，已保留当前结果，请稍后重试") from error
            except asyncio.CancelledError:
                raise
            except Exception as error:
                raise ProviderError("模型调用失败，请检查服务端模型配置与网络") from error
            usage = usage or {}
            actual = usage.get("total_tokens")
            if actual is None and usage.get("input_tokens") is not None:
                actual = usage["input_tokens"] + usage.get("output_tokens", 0)
            estimated = actual is None
            actual = estimate + estimate_tokens(str(content)) if estimated else int(actual)
            def settle(current, db):
                current["tokens_used"] += actual - reservation
                if estimated:
                    current["has_estimated_usage"] = True
                current["model_calls"][key] = {
                    "status": "returned", "tokens": actual, "estimated": estimated,
                    "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                }
                current["tokens_estimated"] = any(
                    call.get("estimated", call.get("status") == "running")
                    for call in current["model_calls"].values()
                )
            self.store.mutate(run_id, settle, event_type="budget.updated", node="budget",
                              title="模型用量已更新", payload={"tokens": actual, "estimated": estimated,
                              "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                              "cumulative_tokens": self.store.get(run_id)["tokens_used"] + actual - reservation})
            try:
                # 模型附带的补充说明可忽略，约定字段仍经过类型、枚举和引用核验。
                parsed = schema.model_validate_json(content, extra="ignore")
            except (ValidationError, ValueError, TypeError) as error:
                fields = []
                if isinstance(error, ValidationError):
                    fields = [{"field": ".".join(str(part) for part in item["loc"]), "type": item["type"], "message": item["msg"]}
                              for item in error.errors(include_input=False, include_url=False)[:10]]
                self.store.emit(run_id, "node.failed", key.split(":")[0], "结构化输出需要修复",
                                {"attempt": attempt + 1, "fields": fields})
                instruction += "\n上一次输出未通过结构校验，请按这些字段错误修复完整 JSON。" + json.dumps(fields, ensure_ascii=False)
                continue
            def complete(current, db):
                current["model_calls"][key].update(status="completed", response=parsed.model_dump())
            completed_title = {
                "understand": "问题理解已完成", "merge": "补充信息已合并", "plan": "查询规划已完成",
                "extract": "经历候选已提取", "verify": "字段证据已核对", "analyze": "缺口分析已完成",
            }.get(key.split(":")[0], "结构化分析已完成")
            self.store.mutate(run_id, complete, event_type="node.completed", node=key.split(":")[0],
                              title=completed_title, span_id=key + f":{attempt}",
                              payload={"duration_ms": int((time.monotonic() - started_at) * 1000)})
            return parsed
        raise ProviderError("模型结构化输出校验失败，已保留当前可用结果")

    async def understand(self, state: GraphState):
        run = self.store.get(state["run_id"])
        if run["profile"]:
            return {"needs_clarification": bool(run["clarification"] and not run["clarification"].get("answers"))}
        result = await self.call_model(
            run["id"], "understand:initial", Understanding,
            "提取用户画像。所有 UserFact 的 source_text 必须是用户输入的原文片段，未知字段为 null 或空列表。"
            "只对会改变检索方向的歧义提出 1—3 个澄清问题，其余未知项写入 unknowns。"
            "用户已经给出明确目标和路径时 questions 为空。target.value 使用简短目标词。"
            "target.value 最多用三个关键词，具体岗位路径保留在 decision_question 和 planned_actions。"
            "专业、学历、年级、在读/在职阶段、起点能力分别提取，保留硕士与博士差别。"
            "focus_dimensions 只列用户明确关心的行动、结果、时间成本、计划、目标或约束。",
            {"question": run["question"]},
        )
        profile = self.validate_profile(result.profile, run["question"])
        questions = list({question.id: question for question in result.questions}.values())[:3]
        clarification = {"id": uuid4().hex, "questions": [q.model_dump() for q in questions], "answers": None} if questions else None
        self.store.change(run["id"], {"profile": profile, "profile_version": 1, "clarification": clarification},
                          event_type="profile.extracted", node="understand", title="已整理你的背景与目标",
                          payload={"profile": profile, "questions": len(questions)})
        return {"needs_clarification": bool(questions), "no_gain_batches": 0}

    @staticmethod
    def validate_profile(profile: Profile, raw: str, previous: dict | None = None) -> dict:
        data = profile.model_dump()
        for name, value in data.items():
            if isinstance(value, dict) and "source_text" in value:
                if clean_text(value["source_text"]) not in clean_text(raw) or not value["source_text"].strip():
                    retained = (previous or {}).get(name)
                    data[name] = retained if retained and clean_text(retained["source_text"]) in clean_text(raw) else None
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                data[name] = [fact for fact in value if fact.get("source_text")
                              and clean_text(fact["source_text"]) in clean_text(raw)]
        if not data.get("target"):
            raise ProviderError("目标原话依据校验未通过，请尝试更明确地描述想探索的方向")
        if data.get("education") and any(term in data["education"]["source_text"] for term in ["研一", "研二", "研三", "研究生", "硕士", "博士"]):
            source = data["education"]["source_text"]
            data["education"]["value"] = "博士研究生" if "博士" in source else "硕士研究生" if "硕士" in source else "研究生"
        return data

    async def clarify(self, state: GraphState):
        run = self.store.get(state["run_id"])
        answer = interrupt(run["clarification"])
        return {"clarification_answer": answer}

    async def merge_answers(self, state: GraphState):
        run = self.store.get(state["run_id"])
        answer = state["clarification_answer"]
        raw = run["question"] + "\n" + "\n".join(answer["answers"].values())
        result = await self.call_model(
            run["id"], "merge:clarification", Understanding,
            "结合原问题和澄清回答更新画像。所有 source_text 来自输入原文，未知信息保留未知。"
            "source_text 必须是一段连续原文，禁止拼接多个句子或回答。target.value 最多三个简短目标关键词，"
            "具体路径、时间条件写入planned_actions/constraints。年级不代表明确的硕士或博士学位。"
            "用户补充优先。此次已经完成集中澄清，questions 返回空列表。",
            {"question": raw, "previous_profile": run["profile"]},
        )
        profile = self.validate_profile(result.profile, raw, previous=run["profile"])
        clarification = {**run["clarification"], "answers": answer["answers"]}
        self.store.change(run["id"], {"profile": profile, "profile_version": 2, "clarification": clarification},
                          event_type="profile.extracted", node="merge", title="已根据补充信息更新画像",
                          payload={"profile": profile})
        return {"needs_clarification": False}

    def validate_queries(self, run: dict, drafts: list) -> list[dict]:
        profile = run["profile"]
        seen = {clean_text(query["query_text"]).lower() for query in run["queries"]}
        plans = []
        education = (profile.get("education") or {}).get("value", "")
        target = profile["target"]["value"]
        major = (profile.get("major") or {}).get("value", "")
        next_index = max((query.get("query_index", query["number"]) for query in run["queries"]), default=0) + 1
        for draft in drafts:
            index = next_index + len(plans)
            terms = " ".join(draft.terms)[:120]
            if "研究生" in education and any(word in terms for word in ["本科", "高中", "专科"]):
                continue
            relaxed = list(draft.relaxed_fields)
            if index <= 2:
                relaxed = []
            if not draft.relaxation_reason:
                relaxed = []
            anchors = [education, target]
            if major and "major" not in relaxed:
                anchors.append(major)
            # Q01 只使用有原话依据的画像，后续查询才加入模型补充词。
            supplements = [] if index == 1 else terms.split()
            words = []
            for part in [*anchors, *supplements, "经历"]:
                for word in part.split():
                    if word and word not in words:
                        words.append(word)
            query_text = " ".join(words)[:180]
            normalized = clean_text(query_text).lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            plan = {"id": uuid4().hex, "query_text": query_text, "purpose": draft.purpose,
                    "query_index": index, "requested_count": run["limits"].get("query_counts", [10, 6, 5, 5])[min(index - 1, 3)],
                    "target_gap": draft.target_gap, "relaxed_fields": relaxed,
                    "relaxation_reason": draft.relaxation_reason if relaxed else "",
                    "preserved_fields": {"education": education, "target": target, "major": "" if "major" in relaxed else major},
                    "profile_version": run["profile_version"]}
            plans.append(plan)
            self.store.emit(run["id"], "query.planned", "plan", "已规划一条检索查询", {"plan": plan})
        return plans

    async def plan_initial(self, state: GraphState):
        run = self.store.get(state["run_id"])
        result = await self.call_model(
            run["id"], "plan:initial", InitialPlan,
            "规划最多两条目的互补的知乎经历查询。terms 只提供精简补充词，程序会添加教育阶段和目标锚点。"
            "返回两条查询。Q01 由程序使用原画像构建，Q02 只用同义表达或少量补充词，保持相同专业与学历。"
            "每条 terms 最多三个简短关键词，不重复画像锚点。relaxed_fields 返回空列表。"
            "禁止把研究生改成本科生，禁止添加与目标无关的领域。relaxed_fields 仅允许 major、experience、time。",
            {"profile": run["profile"]},
        )
        drafts = list(result.queries)
        drafts[0] = QueryDraft(terms=["经历"], purpose="忠实检索用户专业、学历阶段与目标相近的经历",
                               target_gap="相近背景的真实经历")
        if len(drafts) < 2:
            drafts.append(QueryDraft(terms=["准备过程"], purpose="同背景下补充行动路径表达", target_gap="准备行动"))
        plans = self.validate_queries(run, drafts)
        return {"pending_queries": plans, "stop_reason": "" if plans else "no_valid_query"}

    async def execute_search(self, state: GraphState):
        if state.get("stop_reason"):
            return {"batch_hit_ids": []}
        run_id = state["run_id"]
        plans = state.get("pending_queries", [])[:2]
        async def perform(plan):
            current = self.store.get(run_id)
            existing = [query for query in current["queries"] if query["plan_id"] == plan["id"]]
            if existing:
                return [hit["id"] for hit in current["hits"] if hit["query_id"] in {q["id"] for q in existing}]
            retry_of = None
            for attempt in range(2):
                current = self.store.get(run_id)
                try:
                    self.budget_check(current, searching=True)
                except BudgetReached:
                    return []
                query = self.store.reserve_query(run_id, {**plan, "plan_id": plan["id"]}, retry_of)
                if not query:
                    return []
                started = time.monotonic()
                timeout = max(0.1, min(20, current["limits"]["seconds"] - elapsed(current) - current["limits"]["reserve_seconds"]))
                try:
                    result = await asyncio.wait_for(self.search.search(
                        query["query_text"], query.get("requested_count", current["limits"]["results_per_query"]), timeout), timeout=timeout)
                    hits = normalize_hits(run_id, query["id"], result["items"])
                    self.store.complete_query(run_id, query["id"], hits, None,
                                              int((time.monotonic() - started) * 1000), result.get("search_hash", ""))
                    return [hit["id"] for hit in hits]
                except asyncio.CancelledError:
                    raise
                except (ProviderError, asyncio.TimeoutError) as error:
                    message = str(error) if isinstance(error, ProviderError) else "知乎搜索请求超时"
                    self.store.complete_query(run_id, query["id"], [], message,
                                              int((time.monotonic() - started) * 1000))
                    if isinstance(error, ProviderError) and not error.retryable:
                        self.store.change(run_id, {"error": message})
                        return []
                    retry_of = query["id"]
                    if attempt == 0:
                        await asyncio.sleep(0.5)
            return []
        batches = await asyncio.gather(*(perform(plan) for plan in plans))
        return {"batch_hit_ids": [hit_id for batch in batches for hit_id in batch]}

    async def extract(self, state: GraphState):
        run = self.store.get(state["run_id"])
        completed = {(hit["source_id"], hit["text"]) for hit in run["hits"]
                     if run.get("analyses", {}).get(hit["id"], {}).get("status") == "completed"}
        groups = list(run.get("analysis_batches", []))
        assigned = {hit_id for group in groups for hit_id in group["hit_ids"]}
        assigned_signatures = {(hit["source_id"], hit["text"]) for hit in run["hits"] if hit["id"] in assigned}
        unique = {}
        for hit in run["hits"]:
            signature = (hit["source_id"], hit["text"])
            if signature not in assigned_signatures and signature not in completed:
                unique.setdefault(signature, hit)
        queued = sorted(unique.values(), key=lambda hit: -source_priority(hit, run["profile"]))
        for offset in range(0, len(queued), 3):
            ids = [hit["id"] for hit in queued[offset:offset + 3]]
            group_id = hashlib.sha256("".join(ids).encode()).hexdigest()[:16]
            groups.append({"id": group_id, "hit_ids": ids, "status": "pending"})
        self.store.change(run["id"], {"analysis_batches": groups}, event_type="candidates.selected",
                          node="extract", title="已按专业、学历和目标安排候选分析顺序",
                          payload={"queued_sources": len(queued), "batch_size": 3,
                                   "priority": ["major", "education", "target"]})
        changed = 0
        for group in groups:
            if group["status"] == "completed":
                continue
            current = self.store.get(run["id"])
            reserve = 0
            if current["request_count"] < current["limits"]["requests"]:
                reserve = min(14000 if current["request_count"] <= 2 else 6000,
                              int(current["limits"]["tokens"] * 0.25))
            hits = [hit for hit in current["hits"] if hit["id"] in group["hit_ids"]]
            try:
                changed += await self.process_sources(current, group, hits, reserve)
            except BudgetReached as error:
                if error.reason != "token_budget" or not reserve:
                    raise
                self.store.emit(run["id"], "analysis.deferred", "extract", "已为缺口分析和后续补查预留预算",
                                {"reserved_tokens": reserve, **analysis_stats(self.store.get(run["id"]))})
                break
        updated = self.store.get(run["id"])
        coverage = coverage_for(updated["cases"], updated["profile"])
        self.store.change(run["id"], {"coverage": coverage}, event_type="coverage.updated", node="extract",
                          title="案例评分与证据覆盖已更新",
                          payload={"case_count": len(updated["cases"]), "coverage": coverage,
                                   **analysis_stats(updated)})
        return {"no_gain_batches": 0 if changed else state.get("no_gain_batches", 0) + 1}

    async def process_sources(self, run: dict, group: dict, hits: list[dict], reserve: int):
        excerpts = {hit["id"]: relevant_excerpt(hit, run["profile"]) for hit in hits}
        result = await self.call_model(
            run["id"], "extract:" + group["id"], Extraction,
            "从摘要中提取最多四个与用户目标相关的具体人物经历。纯建议、提问和泛泛观点跳过。"
            "专业 major、学历 education、年级 year、职业阶段 career_stage、目标 target、计划 plans、"
            "起点 starting_point、约束 constraints 分别提取。人物身份必须来自经历叙述，不能来自问题标题。"
            "全部字段都是 EvidenceFact，quote 逐字引用摘要，value 只概括引用明确支持的事实。"
            "未披露字段为 null。actions 只记录已发生行动，plans 记录计划，stage_outcomes 记录已发生结果。"
            "面试、Offer 分清，作者自述 subject 统一为 作者，转述者使用稳定人物称呼。"
            "applicability 简述有依据的背景差异。输出尽量简洁，避免各字段重复整段原文。",
            {"profile": run["profile"], "sources": [
                {"source_hit_id": hit["id"], "title": hit["source"]["title"], "text": excerpts[hit["id"]]}
                for hit in hits]}, token_reserve=reserve,
        )
        by_id = {hit["id"]: hit for hit in hits}
        existing_cases = {case["id"]: case for case in run["cases"]}
        validated = []
        candidate_ids = {hit["id"]: [] for hit in hits}
        rejected = 0
        for candidate in result.cases:
            hit = by_id.get(candidate.source_hit_id)
            if not hit:
                rejected += 1
                continue
            case_id = hashlib.sha256((run["id"] + hit["source_id"] + candidate.subject).encode()).hexdigest()[:24]
            candidate_ids[hit["id"]].append(case_id)
            facts = {}
            for name in FACT_LABELS:
                fact = getattr(candidate, name)
                quote = clean_text(fact.quote) if fact else ""
                if quote and quote in hit["text"] and quote in clean_text(excerpts[hit["id"]]):
                    facts[name] = {**fact.model_dump(), "hit_id": hit["id"], "evidence_scope": "summary"}
                elif fact:
                    rejected += 1
            if facts.get("actions") and len(facts) >= 2:
                facts = {**existing_cases.get(case_id, {}).get("facts", {}), **facts}
                validated.append({"id": case_id, "title": candidate.title, "subject": candidate.subject,
                                  "source_id": hit["source_id"], "source": hit["source"], "facts": facts,
                                  "source_nature": candidate.source_nature, "applicability": candidate.applicability})
        def extracted(current, db):
            analyses = current.setdefault("analyses", {})
            for hit in hits:
                analyses[hit["id"]] = {"status": "extracted", "candidate_ids": candidate_ids[hit["id"]],
                                        "priority": source_priority(hit, current["profile"])}
        self.store.mutate(run["id"], extracted, event_type="candidates.extracted", node="extract",
                          title="已提取候选，正在核验与评分",
                          payload={"candidate_count": sum(map(len, candidate_ids.values())), "rejected_fields": rejected})
        changed = 0
        for offset in range(0, len(validated), 2):
            batch = validated[offset:offset + 2]
            referenced_ids = {fact["hit_id"] for case in batch for fact in case["facts"].values()}
            review = await self.call_model(
                run["id"], "verify:" + group["id"] + f":{offset}", EvidenceReview,
                "逐项核对事实 value、title、applicability 是否由引用及上下文直接支持，每项输出 supported。"
                "分清计划与已完成、面试与Offer。实际人物经历必须有已发生行动，纯建议或假设 actual_experience=false。"
                "relevant 判断经历与用户目标是否相关。background_match 比较背景，differences 仅写有依据的差异。"
                "每个经历在 assessments 中对用户已提供的六个比较维度逐项评分并给简短理由及 evidence_fields。"
                "level 使用0/0.25/0.5/0.75/1：明确冲突/差异大/部分相似/接近/一致，材料缺失为null。"
                "专业相同给1，相邻专业可0.75，其他专业按真实差异评分。学历同时比较学位、年级、在读或在职阶段。"
                "用户研究生与本科生的 education 至多0.25，学生找实习与在职多年转岗至多0.5。"
                "目标比较岗位和实习/全职，计划比较路径，起点比较能力与已做行动，约束比较投入时间、地域等。"
                "评分只能引用本案例已核验的对应字段，缺少对应字段保留null。不要用泛泛背景字段代替具体专业学历引用。"
                "目标与计划不得从用户画像移植到案例中，未知年份、专业等一律保留未知。",
                {"cases": [{"case_index": index, "facts": case["facts"], "title": case["title"],
                            "applicability": case["applicability"]} for index, case in enumerate(batch)],
                 "profile": run["profile"], "comparison_dimensions": comparison_profile(run["profile"]),
                 "sources": {hit["id"]: relevant_excerpt(hit, run["profile"])
                             for hit in run["hits"] if hit["id"] in referenced_ids}},
                token_reserve=reserve,
            )
            judgments = {}
            for item in review.judgments:
                key = (item.case_index, item.field)
                judgments[key] = judgments.get(key, True) and item.supported
            reviewed = []
            for index, case in enumerate(batch):
                experiences = [item for item in review.experiences if item.case_index == index]
                if len(experiences) != 1:
                    continue
                experience = experiences[0]
                if not experience.actual_experience or not experience.relevant:
                    continue
                case["background_match"] = experience.background_match
                case["background_differences"] = experience.differences
                case["facts"] = {field: fact for field, fact in case["facts"].items() if judgments.get((index, field), False)}
                if not judgments.get((index, "title"), False):
                    case["title"] = "与" + run["profile"]["target"]["value"] + "相关的经历"
                if not judgments.get((index, "applicability"), False):
                    case["applicability"] = "具体适用条件请结合字段证据核对。"
                case["matching"] = score_case(case, run["profile"], [item.model_dump() for item in experience.assessments])
                if case["facts"].get("actions") and len(case["facts"]) >= 2:
                    reviewed.append(case)
            changed += self.store.save_cases(run["id"], reviewed)
            self.store.emit(run["id"], "cases.ranked", "verify", "案例已完成字段评分",
                            {"cases": [{"id": case["id"], "title": case["title"], "matching": case["matching"]}
                                       for case in reviewed]})
        def completed(current, db):
            for hit in hits:
                current["analyses"][hit["id"]]["status"] = "completed"
            for saved in current["analysis_batches"]:
                if saved["id"] == group["id"]:
                    saved["status"] = "completed"
        self.store.mutate(run["id"], completed, event_type="sources.analyzed", node="extract",
                          title="一批来源已完成分析", payload={"source_count": len(hits)})
        return changed

    def after_extraction(self, state: GraphState):
        if state.get("stop_reason"):
            return "finalize"
        run = self.store.get(state["run_id"])
        if run.get("error") or run["request_count"] >= run["limits"]["requests"]:
            return "finalize"
        if state.get("no_gain_batches", 0) >= 2 and not analysis_stats(run)["pending_sources"]:
            return "finalize"
        try:
            self.budget_check(run, searching=True)
        except BudgetReached:
            return "finalize"
        return "analyze"

    async def analyze(self, state: GraphState):
        run = self.store.get(state["run_id"])
        result = await self.call_model(
            run["id"], f"analyze:{run['request_count']}", GapAnalysis,
            "评估当前经历证据对用户问题的覆盖情况。给出最重要缺口，并区分可检索信息 search 与"
            "只能通过用户实践验证的信息 practice。若值得继续检索，生成一条针对缺口的 next_query。"
            "根据用户 focus_dimensions 判断重要缺口，专业、学历、目标为用户已知时必须考虑匹配程度。"
            "只有关键维度覆盖充分、已有足够高匹配案例时 sufficient=true，此时只保留practice缺口。"
            "dimension 使用 major/education/target/plans/starting_point/constraints/actions/stage_outcomes/time_and_cost。"
            "next_query 最多三个简短补充词，禁止重复 previous_queries。核心背景由程序添加。"
            "仅在已有检索证据表明同专业案例不足时可放宽major，并填写具体relaxation_reason，禁止改变学历。",
            {"profile": run["profile"], "coverage": run["coverage"],
             "cases": [{"id": case["id"], "facts": {name: fact["value"] for name, fact in case["facts"].items()},
                        "matching": {key: case.get("matching", {}).get(key) for key in ("score", "tier", "field_coverage")},
                        "applicability": case["applicability"]}
                       for case in sorted(run["cases"], key=rank_key)[:8]],
             "previous_queries": [{"query": q["query_text"], "result_count": q["result_count"]}
                                  for q in run["queries"]],
             "remaining_requests": run["limits"]["requests"] - run["request_count"],
             "analysis_stats": analysis_stats(run)},
        )
        gaps = [gap.model_dump() for gap in result.gaps]
        self.store.change(run["id"], {"gaps": gaps}, event_type="coverage.updated", node="analyze",
                          title="已评估下一步检索价值", payload={"explanation": result.explanation, "gaps": gaps})
        required = coverage_for(run["cases"], run["profile"])
        if result.sufficient and required and all(item["status"] == "clear" for item in required) and not any(
            gap.kind == "search" for gap in result.gaps
        ):
            self.store.emit(run["id"], "coverage.sufficient", "analyze", "关键证据已覆盖，提前生成报告",
                            {"explanation": result.explanation, "skipped_queries": 4 - run["request_count"]})
            return {"stop_reason": "coverage_met"}
        plans = self.validate_queries(run, [result.next_query]) if result.next_query else []
        return {"pending_queries": plans, "stop_reason": "" if plans else "no_valid_query"}

    async def finalize(self, state: GraphState):
        self.finish(state["run_id"], state.get("stop_reason") or "", state.get("no_gain_batches", 0))
        return {}

    def finish(self, run_id: str, reason: str, no_gain_batches: int = 0, error: str | None = None):
        run = self.store.get(run_id)
        if run["status"] in ("finished", "failed", "cancelled"):
            return
        if not reason:
            if run.get("error"):
                reason = "service_error"
            elif run["request_count"] >= run["limits"]["requests"]:
                reason = "request_limit"
            elif elapsed(run) >= run["limits"]["seconds"] - run["limits"]["reserve_seconds"]:
                reason = "time_budget"
            elif run["limits"]["tokens"] - run["tokens_used"] < 2000:
                reason = "token_budget"
            elif no_gain_batches >= 2:
                reason = "no_new_evidence"
            else:
                reason = "no_valid_query"
        self.store.settle_pending(run_id, reason)
        run = self.store.get(run_id)
        coverage = coverage_for(run["cases"], run["profile"])
        gaps = list(run["gaps"])
        for item in coverage:
            if item["status"] != "clear" and not any(gap["dimension"] == item["dimension"] for gap in gaps):
                gaps.append({"dimension": item["dimension"], "description": item["label"] + "证据仍需补充", "kind": "search"})
        complete = reason == "coverage_met" and all(item["status"] == "clear" for item in coverage)
        successful = any(query["status"] == "completed" for query in run["queries"])
        result_status = "complete" if complete else "partial"
        if not run["cases"]:
            result_status = "empty" if successful else "unavailable"
        stats = analysis_stats(run)
        ranked = sorted(run["cases"], key=rank_key)
        report = {
            "summary": (f"检索返回 {stats['hits']} 条内容，去重后 {stats['sources']} 个来源，"
                        f"完成分析 {stats['analyzed_sources']} 个来源，保留 {stats['cases']} 个案例，"
                        f"案例实际引用 {stats['cited_sources']} 个来源。"),
            "coverage": coverage, "gaps": gaps, "case_ids": [case["id"] for case in ranked],
            "top_case_ids": [case["id"] for case in ranked[:5]],
            "stats": {"requests": run["request_count"], **stats,
                      "tokens": run["tokens_used"], "active_seconds": round(elapsed(run), 2)},
            "stop_reason": reason, "result_status": result_status,
            "evidence_note": "案例依据知乎返回摘要整理，重要字段保留引用，时间与结果缺失项仍需进一步验证。",
        }
        status = "cancelled" if reason == "cancelled" else "finished"
        if reason == "service_error" and not successful and not run["cases"]:
            status = "failed"
        self.store.change(run_id, {"status": status, "result_status": result_status, "stop_reason": reason,
                                  "report": report, "coverage": coverage, "gaps": gaps,
                                  "active_seconds": elapsed(run), "clock_started_at": None,
                                  "error": error or run.get("error")},
                          event_type="report.ready", node="finalize", title="本次检索报告已整理",
                          payload={"report": report})
        self.store.emit(run_id, "run." + status, "finalize", "任务已取消" if status == "cancelled" else "本次检索已结束",
                        {"status": status, "result_status": result_status, "stop_reason": reason})
