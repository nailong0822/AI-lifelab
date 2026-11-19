"""随航伙伴对话、可追溯操作和记忆的数据契约。"""
from typing import Literal
from pydantic import Field
from .models import Contract
from .web_models import WebCitation

Mode = Literal['auto', 'listen', 'solve']

class CompanionMessage(Contract):
    client_message_id: str = Field(min_length=8, max_length=100)
    text: str = Field(min_length=1, max_length=6000)
    mode: Mode = 'auto'
    stage_id: str | None = None
    task_id: str | None = None
    web_search: Literal['auto', 'off'] = 'auto'

class CompanionAction(Contract):
    kind: Literal['progress', 'revision', 'memory', 'achievement']
    title: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=1, max_length=1000, description='本轮用户消息中的连续原文，不得从他人案例或助手建议提取')
    value: str = Field(default='', max_length=1500)
    stage_id: str = ''
    task_id: str = ''
    status: Literal['pending', 'in_progress', 'blocked', 'completed', 'skipped'] = 'pending'
    memory_kind: Literal['preference', 'constraint', 'ability'] = 'preference'
    automatic: bool = False

class CompanionReply(Contract):
    intent: Literal['support', 'help', 'progress', 'adjustment', 'chat']
    safety: Literal['normal', 'urgent'] = 'normal'
    message: str = Field(min_length=2, max_length=6000)
    small_step: str = Field(default='', max_length=400)
    followups: list[str] = Field(default_factory=list, max_length=3)
    evidence_ids: list[str] = Field(default_factory=list, max_length=4)
    actions: list[CompanionAction] = Field(default_factory=list, max_length=2)
    web_citations: list[WebCitation] = Field(default_factory=list, max_length=4)
    web_answer_status: Literal['not_used','supported','insufficient'] = 'not_used'

class ActionDecision(Contract):
    approve: bool

class MemoryUpdate(Contract):
    value: str = Field(min_length=1, max_length=500)
