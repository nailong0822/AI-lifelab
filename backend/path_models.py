"""人生路径、用户选择和进度更新的数据契约。"""

from typing import Literal

from pydantic import Field, model_validator

from .models import Contract, Question


class Basis(Contract):
    kind: Literal["case", "synthesis", "hypothesis"]
    explanation: str = Field(min_length=1, max_length=400)
    evidence_ids: list[str] = Field(default_factory=list, max_length=4)
    validation_action: str = Field(default="", max_length=300)


class Candidate(Contract):
    title: str = Field(min_length=2, max_length=80)
    goal: str = Field(min_length=2, max_length=250)
    approach: str = Field(min_length=2, max_length=350)
    suitable_conditions: list[str] = Field(min_length=1, max_length=4)
    first_action: str = Field(min_length=2, max_length=250)
    effort: str = Field(min_length=2, max_length=200)
    difficulties: list[str] = Field(min_length=1, max_length=4)
    basis: Basis


class CandidateProposal(Contract):
    questions: list[Question] = Field(default_factory=list, max_length=3)
    paths: list[Candidate] = Field(default_factory=list, max_length=4)


class Stage(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,60}$")
    title: str = Field(min_length=2, max_length=80)
    objective: str = Field(min_length=2, max_length=300)
    completion_criteria: str = Field(min_length=2, max_length=350)
    depends_on: list[str] = Field(default_factory=list, max_length=5)
    effort_hours_min: float | None = Field(default=None, ge=0, le=2000)
    effort_hours_max: float | None = Field(default=None, ge=0, le=4000)
    already_completed: bool = False
    user_evidence: list[str] = Field(default_factory=list, max_length=3)
    basis: Basis

    @model_validator(mode="after")
    def check_effort(self):
        if self.effort_hours_min is not None and self.effort_hours_max is not None:
            if self.effort_hours_min > self.effort_hours_max:
                raise ValueError("预计投入的最小值应小于最大值")
        return self


class PlanOutline(Contract):
    title: str = Field(min_length=2, max_length=100)
    goal: str = Field(min_length=2, max_length=350)
    stages: list[Stage] = Field(min_length=4, max_length=6)
    limitations: list[str] = Field(default_factory=list, max_length=6)


class Task(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,45}$")
    title: str = Field(min_length=2, max_length=100)
    kind: Literal["action", "experiment", "milestone"]
    description: str = Field(min_length=2, max_length=450)
    output: str = Field(min_length=2, max_length=350)
    completion_criteria: str = Field(min_length=2, max_length=450)
    depends_on: list[str] = Field(default_factory=list, max_length=4)
    effort_hours: float | None = Field(default=None, ge=0, le=1000)
    skills: list[str] = Field(default_factory=list, max_length=4)
    help_hint: str = Field(min_length=2, max_length=350)
    basis: Basis


class StageDetails(Contract):
    tasks: list[Task] = Field(min_length=2, max_length=4)


class PlanningReview(Contract):
    issues: list[str] = Field(default_factory=list, max_length=3, description="仅阻断性错误：明确违反用户硬约束、伪造证据或承诺结果。无错误为空，不能把正面评价或改进偏好列入。")
    suggestions: list[str] = Field(default_factory=list, max_length=3, description="非阻断的可选改进，不影响保存或继续")


class PathResponse(Contract):
    input_id: str
    answers: dict[str, str] | None = None
    candidate_id: str | None = None
    custom_goal: str = Field(default="", max_length=1500)
    approve: bool | None = None


class PathSelection(Contract):
    candidate_id: str | None = None
    custom_goal: str = Field(default="", max_length=1500)
    version: int = Field(ge=0)


class PlanRevision(Contract):
    instruction: str = Field(min_length=5, max_length=3000)
    version: int = Field(ge=1)


class StageRequest(Contract):
    stage_id: str
    version: int = Field(ge=1)


class ProgressUpdate(StageRequest):
    task_id: str
    status: Literal["pending", "in_progress", "blocked", "completed", "skipped"]
    note: str = Field(default="", max_length=2000)


class JourneyUpdate(Contract):
    paused: bool
