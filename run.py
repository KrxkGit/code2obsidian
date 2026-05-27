#!/usr/bin/env python3
"""
向后兼容的入口脚本。
推荐使用：
    pip install -e .
    code2obsidian -s ./src -o /path/to/Vault
或：
    python -m code2obsidian -s ./src -o /path/to/Vault
"""

from __future__ import annotations

import os
import sys


def _bootstrap() -> None:
    """允许直接在源码目录运行而无需 pip install。"""
    here = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.join(here, "src")
    if os.path.isdir(src_dir) and src_dir not in sys.path:
        sys.path.insert(0, src_dir)


if __name__ == "__main__":
    _bootstrap()
    # 通过 importlib 间接加载，避免静态分析器在未安装包时误报 reportMissingImports
    import importlib

    cli = importlib.import_module("code2obsidian.cli")
    sys.exit(cli.main())