"""Contracts for private journey reviews and explicitly shared experiences."""
from typing import Literal
from pydantic import Field, field_validator
from .models import Contract

Outcome = Literal['achieved', 'milestone', 'changed', 'paused', 'stopped']
CaseField = Literal['person_context', 'major', 'education', 'year', 'career_stage',
                    'target', 'plans', 'starting_point', 'constraints', 'actions',
                    'stage_outcomes', 'time_and_cost', 'event_time']


class JourneyFinish(Contract):
    request_id: str = Field(min_length=8, max_length=100)
    version: int = Field(ge=1)
    outcome: Outcome
    reflection: str = Field(min_length=5, max_length=4000)

    @field_validator('reflection',mode='before')
    @classmethod
    def trim_reflection(cls,value):
        return value.strip() if isinstance(value,str) else value


class ExperienceReference(Contract):
    source_id: str = Field(max_length=120)
    quote: str = Field(min_length=1, max_length=600)


class ExperienceFact(Contract):
    field: CaseField
    value: str = Field(min_length=1, max_length=800)
    references: list[ExperienceReference] = Field(min_length=1, max_length=4)


class ExperienceExtraction(Contract):
    facts: list[ExperienceFact] = Field(default_factory=list, max_length=30)


class ExperienceDocument(Contract):
    title: str = Field(min_length=2, max_length=100)
    summary: str = Field(min_length=5, max_length=2500)
    fields: dict[CaseField, str] = Field(default_factory=dict, max_length=13)
    lessons: str = Field(default='', max_length=1200)

    @field_validator('fields')
    @classmethod
    def bound_fields(cls, fields):
        if any(len(value)>4000 for value in fields.values()) or sum(map(len,fields.values()))>20000:
            raise ValueError('案例字段过长，请精简')
        return fields


class ExperienceEdit(Contract):
    revision: int = Field(ge=1)
    document: ExperienceDocument


class ExperienceConsent(Contract):
    revision: int = Field(ge=1)
    confirmed: Literal[True]
