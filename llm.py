"""检索 Agent 共用的 DeepSeek 模型入口。"""

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


def create_chat_model(*, max_retries: int = 2, timeout: float = 60, api_key: str | None = None) -> ChatOpenAI:
    """从项目 .env 或进程环境变量读取配置并创建模型。"""
    load_dotenv(Path(__file__).resolve().parent / ".env")

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip() if api_key is None else api_key.strip()
    if not api_key:
        raise ValueError("请先在项目 .env 中填写 DEEPSEEK_API_KEY。")

    base_url = os.getenv("DEEPSEEK_BASE_URL", "").strip() or "https://api.deepseek.com"
    model = os.getenv("DEEPSEEK_MODEL", "").strip() or "deepseek-flash"

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
    )
