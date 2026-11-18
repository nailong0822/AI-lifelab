"""候选优先级、可解释的字段评分与任务统计。"""

import re

FACT_LABELS = {
    "person_context": "人物背景", "major": "专业", "education": "学历",
    "year": "年级", "career_stage": "职业阶段", "target": "目标方向",
    "plans": "计划与路径", "starting_point": "起点能力", "constraints": "现实约束",
    "actions": "采取的行动", "stage_outcomes": "阶段结果",
    "time_and_cost": "时间与成本", "event_time": "经历时间",
}

SCORE_WEIGHTS = {"major": 25, "education": 20, "target": 25, "plans": 15,
                 "starting_point": 10, "constraints": 5}
SCORE_LABELS = {**FACT_LABELS, "education": "学历与阶段", "plans": "计划与路径",
                "starting_point": "起点能力与行动"}
SCORE_FIELDS = {
    "major": {"major"}, "education": {"education", "year", "career_stage"},
    "target": {"target"}, "plans": {"plans", "actions"},
    "starting_point": {"starting_point", "actions"},
    "constraints": {"constraints", "time_and_cost"},
}


def comparison_profile(profile: dict) -> dict:
    """只激活用户明确提供的维度，权重在一次任务内保持一致。"""
    return {
        "major": [profile["major"]] if profile.get("major") else [],
        "education": [profile[key] for key in ("education", "year", "career_stage") if profile.get(key)],
        "target": [profile["target"]] if profile.get("target") else [],
        "plans": profile.get("planned_actions", []),
        "starting_point": ([profile["starting_point"]] if profile.get("starting_point") else [])
                          + profile.get("completed_actions", []),
        "constraints": profile.get("constraints", []),
    }


def score_case(case: dict, profile: dict, assessments: list[dict]) -> dict:
    user = comparison_profile(profile)
    total_weight = sum(weight for name, weight in SCORE_WEIGHTS.items() if user[name])
    dimensions = []
    levels = {}
    for name, base_weight in SCORE_WEIGHTS.items():
        weight = base_weight * 100 / total_weight if user[name] and total_weight else 0
        items = [item for item in assessments if item["dimension"] == name]
        assessment = items[0] if len(items) == 1 else {}
        evidence = sorted(set(assessment.get("evidence_fields", [])) & SCORE_FIELDS[name] & case["facts"].keys())
        level = assessment.get("level") if weight and evidence else None
        levels[name] = level
        reason = assessment.get("reason") or "案例材料未提供可核验的对应信息"
        if not weight:
            reason = "用户未提供该维度，本次评分未启用"
        elif level is None:
            reason = "案例对应字段缺少已核验引用，保留未知"
        dimensions.append({
            "dimension": name, "label": SCORE_LABELS[name], "weight": round(weight, 4),
            "level": level, "contribution": round(weight * (level or 0), 4),
            "reason": reason, "user_facts": user[name], "evidence_fields": evidence,
        })
    major = levels["major"]
    education = levels["education"]
    target = levels["target"]
    same_major = not user["major"] or major == 1
    same_stage = not user["education"] or (education is not None and education >= 0.75)
    related_target = target is not None and target >= 0.75
    tier = 3
    if same_major and same_stage and related_target:
        tier = 1
    elif same_stage and target is not None and target >= 0.5:
        tier = 2
    return {
        "version": 1, "score": round(sum(item["contribution"] for item in dimensions), 1),
        "field_coverage": round(sum(item["weight"] for item in dimensions if item["level"] is not None), 1),
        "tier": tier, "tier_label": {1: "背景接近", 2: "路径可参考", 3: "补充参考"}[tier],
        "dimensions": dimensions,
    }


def rank_key(case: dict):
    match = case.get("matching") or {}
    return (match.get("tier", 4), -match.get("score", 0), -match.get("field_coverage", 0), case["id"])


def coverage_for(cases: list[dict], profile: dict | None = None) -> list[dict]:
    profile = profile or {}
    required = list(dict.fromkeys(["actions", *profile.get("focus_dimensions", ["stage_outcomes"])]))
    required += [name for name in ("major", "education", "target") if profile.get(name)]
    rows = []
    for field in dict.fromkeys(required):
        supported = []
        for case in cases:
            matching = case.get("matching")
            # 历史案例保持可读，新案例的覆盖只计入背景有参考价值的经历。
            eligible = matching is None or matching["tier"] <= 2
            if field in ("major", "education", "target") and matching:
                dimension = next(item for item in matching["dimensions"] if item["dimension"] == field)
                minimum = 1 if field == "major" else 0.75
                eligible = eligible and dimension["level"] is not None and dimension["level"] >= minimum
            if eligible and field in case["facts"]:
                supported.append(case)
        count = len({case["source_id"] for case in supported})
        rows.append({"dimension": field, "label": FACT_LABELS[field],
                     "status": "clear" if count >= 2 else "partial" if count else "missing",
                     "case_ids": [case["id"] for case in supported]})
    return rows


def source_priority(hit: dict, profile: dict) -> int:
    text = (hit["source"]["title"] + " " + hit["text"]).lower()
    major = (profile.get("major") or {}).get("value", "").replace("专业", "").lower()
    education = (profile.get("education") or {}).get("value", "")
    target = (profile.get("target") or {}).get("value", "")
    target_terms = re.findall(r"[a-zA-Z]{2,}|AI|实习|软件|开发|考研|留学|转码", target)
    score = 25 if major and major in text else 0
    stage_terms = [education]
    if "研究生" in education:
        stage_terms = ["研究生", "硕士", "博士", "研一", "研二", "研三"]
    score += 20 if any(term and term in text for term in stage_terms) else 0
    score += 25 if any(term.lower() in text for term in target_terms) else 0
    return score


def relevant_excerpt(hit: dict, profile: dict, limit: int = 1800) -> str:
    text = hit["text"]
    if len(text) <= limit:
        return text
    parts = []
    for sentence in re.split(r"(?<=[。！？；])", text):
        parts.extend(sentence[index:index + 400] for index in range(0, len(sentence), 400))
    ranked = sorted(range(len(parts)), key=lambda index: -source_priority(
        {"source": {"title": ""}, "text": parts[index]}, profile))
    selected = {0}
    length = len(parts[0])
    for index in ranked:
        if index not in selected and length + len(parts[index]) + 5 <= limit:
            selected.add(index)
            length += len(parts[index]) + 5
    return "\n[…]\n".join(parts[index] for index in sorted(selected))


def analysis_stats(run: dict) -> dict:
    analyses = run.get("analyses", {})
    signatures = {(hit["source_id"], hit["text"]) for hit in run["hits"]
                  if analyses.get(hit["id"], {}).get("status") == "completed"}
    pending = {hit["source_id"] for hit in run["hits"] if (hit["source_id"], hit["text"]) not in signatures}
    sources = {hit["source_id"] for hit in run["hits"]}
    candidates = {case_id for item in analyses.values() for case_id in item.get("candidate_ids", [])}
    cited = {case["source_id"] for case in run["cases"]}
    return {"hits": len(run["hits"]), "sources": len(sources),
            "analyzed_sources": len(sources - pending), "pending_sources": len(pending),
            "candidates": len(candidates), "cases": len(run["cases"]), "cited_sources": len(cited)}
