"""服务端配置，凭证只在后端使用。"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    data_dir: Path = ROOT / ".data"
    max_requests: int = 4
    results_per_query: int = 5
    query_counts: tuple[int, ...] = (10, 6, 5, 5)
    active_seconds: float = 180
    token_budget: int = 100_000
    finalization_seconds: float = 10
    path_candidate_tokens: int = 80_000
    path_plan_tokens: int = 80_000
    path_revision_tokens: int = 80_000
    companion_tokens: int = 80_000
    companion_seconds: float = 60
    companion_web_tokens: int = 100_000
    companion_web_seconds: float = 90
    web_search_seconds: float = 40
    web_evidence_tokens: int = 10000
    web_context_tokens: int = 18000
    experience_tokens: int = 80000
    experience_seconds: float = 180
    web_cache_seconds: int = 1800
    tavily_key: str = field(default='', repr=False)
    deepseek_key: str = field(default="", repr=False)
    zhihu_secret: str = field(default="", repr=False)

    @classmethod
    def load(cls) -> "Settings":
        values = {**dotenv_values(ROOT / ".env"), **os.environ}
        return cls(
            data_dir=Path(values.get("LIFELAB_DATA_DIR") or ROOT / ".data"),
            active_seconds=float(values.get("RETRIEVAL_TIME_BUDGET") or 180),
            token_budget=int(values.get("RETRIEVAL_TOKEN_BUDGET") or 100_000),
            path_candidate_tokens=int(values.get("PATH_CANDIDATE_TOKEN_BUDGET") or 80_000),
            path_plan_tokens=int(values.get("PATH_PLAN_TOKEN_BUDGET") or 80_000),
            path_revision_tokens=int(values.get("PATH_REVISION_TOKEN_BUDGET") or 80_000),
            companion_tokens=int(values.get("COMPANION_TOKEN_BUDGET") or 80_000),
            companion_seconds=float(values.get("COMPANION_TIME_BUDGET") or 60),
            companion_web_tokens=int(values.get('COMPANION_WEB_TOKEN_BUDGET') or 100_000),
            companion_web_seconds=float(values.get('COMPANION_WEB_TIME_BUDGET') or 90),
            web_search_seconds=float(values.get('WEB_SEARCH_TIME_BUDGET') or 40),
            web_evidence_tokens=int(values.get('WEB_EVIDENCE_TOKEN_BUDGET') or 10000),
            web_context_tokens=int(values.get('WEB_CONTEXT_TOKEN_BUDGET') or 18000),
            experience_tokens=int(values.get('EXPERIENCE_TOKEN_BUDGET') or 80000),
            experience_seconds=float(values.get('EXPERIENCE_TIME_BUDGET') or 180),
            web_cache_seconds=int(values.get('WEB_SEARCH_CACHE_SECONDS') or 1800),
            tavily_key=values.get('TAVILY_API_KEY', '') or '',
            deepseek_key=values.get("DEEPSEEK_API_KEY", "") or "",
            zhihu_secret=values.get("ZHIHU_ACCESS_SECRET", "") or "",
        )
