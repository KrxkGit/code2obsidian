"""统一日志配置。"""

from __future__ import annotations

import logging

logger = logging.getLogger("code2obsidian")


def setup_logging(verbose: bool = False) -> None:
    """初始化全局日志。verbose=True 时输出 DEBUG 级别。"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
