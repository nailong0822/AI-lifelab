"""工作流、接口和模型结构化输出的数据契约。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserFact(Contract):
    value: str = Field(max_length=300)
    source_text: str = Field(max_length=500)


class Question(Contract):
    id: str = Field(pattern=r"^[a-z_]{1,40}$")
    question: str = Field(min_length=2, max_length=180)
    reason: str = Field(max_length=200)


class Profile(Contract):
    background: list[UserFact] = Field(default_factory=list, max_length=8)
    education: UserFact | None = None
    major: UserFact | None = None
    year: UserFact | None = None
    career_stage: UserFact | None = None
    starting_point: UserFact | None = None
    target: UserFact
    decision_question: str = Field(max_length=300)
    planned_actions: list[UserFact] = Field(default_factory=list, max_length=6)
    completed_actions: list[UserFact] = Field(default_factory=list, max_length=6)
    observed_outcomes: list[UserFact] = Field(default_factory=list, max_length=6)
    constraints: list[UserFact] = Field(default_factory=list, max_length=8)
    alternatives: list[str] = Field(default_factory=list, max_length=5)
    unknowns: list[str] = Field(default_factory=list, max_length=8)
    focus_dimensions: list[Literal["actions", "stage_outcomes", "time_and_cost", "plans", "target", "constraints"]] = Field(default_factory=lambda: ["actions", "stage_outcomes"], max_length=6)


class Understanding(Contract):
    profile: Profile
    questions: list[Question] = Field(default_factory=list, max_length=3)


class QueryDraft(Contract):
    terms: list[str] = Field(min_length=1, max_length=12)
    purpose: str = Field(min_length=1, max_length=240)
    target_gap: str = Field(max_length=240)
    relaxed_fields: list[Literal["major", "experience", "time"]] = Field(default_factory=list)
    relaxation_reason: str = Field(default="", max_length=240)


class InitialPlan(Contract):
    queries: list[QueryDraft] = Field(min_length=1, max_length=2)


class EvidenceFact(Contract):
    value: str = Field(min_length=1, max_length=400)
    quote: str = Field(min_length=1, max_length=600)


class CaseCandidate(Contract):
    source_hit_id: str
    subject: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=100)
    source_nature: Literal["self_report", "third_party", "unclear"]
    person_context: EvidenceFact | None = None
    major: EvidenceFact | None = None
    education: EvidenceFact | None = None
    year: EvidenceFact | None = None
    career_stage: EvidenceFact | None = None
    target: EvidenceFact | None = None
    plans: EvidenceFact | None = None
    starting_point: EvidenceFact | None = None
    constraints: EvidenceFact | None = None
    actions: EvidenceFact | None = None
    stage_outcomes: EvidenceFact | None = None
    time_and_cost: EvidenceFact | None = None
    event_time: EvidenceFact | None = None
    applicability: str = Field(max_length=400)


class Extraction(Contract):
    cases: list[CaseCandidate] = Field(default_factory=list, max_length=6)


class EvidenceJudgment(Contract):
    case_index: int = Field(ge=0)
    field: Literal["person_context", "major", "education", "year", "career_stage", "target", "plans", "starting_point", "constraints", "actions", "stage_outcomes", "time_and_cost", "event_time", "title", "applicability"]
    supported: bool


class DimensionAssessment(Contract):
    dimension: Literal["major", "education", "target", "plans", "starting_point", "constraints"]
    level: Literal[0, 0.25, 0.5, 0.75, 1] | None
    reason: str = Field(max_length=180)
    evidence_fields: list[str] = Field(default_factory=list, max_length=13)


class ExperienceJudgment(Contract):
    case_index: int = Field(ge=0)
    actual_experience: bool
    relevant: bool
    background_match: Literal["close", "partial", "distant", "unknown"]
    differences: list[str] = Field(default_factory=list, max_length=4)
    assessments: list[DimensionAssessment] = Field(default_factory=list, max_length=6)


class EvidenceReview(Contract):
    judgments: list[EvidenceJudgment] = Field(default_factory=list, max_length=40)
    experiences: list[ExperienceJudgment] = Field(max_length=2)


class Gap(Contract):
    dimension: str = Field(max_length=80)
    description: str = Field(max_length=240)
    kind: Literal["search", "practice"]


class GapAnalysis(Contract):
    sufficient: bool
    explanation: str = Field(max_length=400)
    gaps: list[Gap] = Field(default_factory=list, max_length=8)
    next_query: QueryDraft | None = None


class RunInput(Contract):
    question: str = Field(min_length=5, max_length=6000)

    @field_validator("question", mode="before")
    @classmethod
    def trim_question(cls, value):
        return value.strip() if isinstance(value, str) else value


class ResumeInput(Contract):
    clarification_id: str
    answers: dict[str, str]


