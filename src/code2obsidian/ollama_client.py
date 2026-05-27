"""本地 Ollama 摘要客户端。"""

from __future__ import annotations

import re
from typing import Any

from .logging_utils import logger
from .models import FileNode

_THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def get_ai_summary(
    session: Any,
    api_url: str,
    model_name: str,
    filename: str,
    node: FileNode,
    timeout: int,
    retries: int,
) -> str:
    """请求本地 Ollama 进行轻量摘要，自带重试与噪声清洗。"""
    if not node.classes and not node.functions:
        return "纯配置、资源或无导出符号文件。"

    # 延迟 import，让核心模块在未安装 requests 的环境也能被导入
    import requests  # type: ignore

    skeleton = (
        f"File: {filename}\n"
        "Classes:\n" + "\n".join(node.classes[:30]) + "\n"
        "Functions:\n" + "\n".join(node.functions[:60])
    )
    prompt = (
        "你是一个资深的混编架构师。请用一句话（不超过30字）极其精准地概括以下代码文件的核心业务职责。"
        "不需要任何问候和废话，直接输出概括：\n\n" + skeleton
    )

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": 2048, "temperature": 0.1},
    }

    for attempt in range(retries + 1):
        try:
            resp = session.post(api_url, json=payload, timeout=timeout)
            if resp.status_code == 200:
                text = resp.json().get("response", "").strip()
                text = _THINK_RE.sub("", text).strip()
                return text or "代码核心模块。"
            logger.debug(
                "LLM HTTP %d (attempt %d): %.200s",
                resp.status_code, attempt, resp.text,
            )
        except requests.RequestException as exc:
            logger.debug("LLM 请求异常 (attempt %d): %s", attempt, exc)
    return "代码核心模块。"
