"""Universal Ctags 流式扫描封装。"""

from __future__ import annotations

import json
import subprocess
from typing import Iterable

from .logging_utils import logger


def run_ctags(source_dir: str) -> Iterable[dict]:
    """流式调用 ctags 并逐行 yield JSON 对象，避免大型仓库 stdout 撑爆内存。"""
    logger.info("⏳ [1/3] 调用 Universal Ctags 扫描: %s", source_dir)
    cmd = ["ctags", "-R", "--output-format=json", "--fields=+nKsS", source_dir]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except FileNotFoundError:
        logger.error("❌ 未找到 ctags 可执行文件，请先 'brew install universal-ctags'")
        return

    assert proc.stdout is not None
    count = 0
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
            count += 1
        except json.JSONDecodeError:
            logger.debug("跳过无法解析的 ctags 行: %.120s", line)

    err = proc.stderr.read() if proc.stderr else ""
    ret = proc.wait()
    if ret != 0:
        logger.error("❌ Ctags 退出码 %d: %s", ret, err.strip())
    logger.debug("ctags 共产出 %d 条符号", count)
