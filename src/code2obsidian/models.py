"""核心数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Set


@dataclass
class FileNode:
    """单个源码文件聚合后的符号信息。"""

    classes: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    members: List[str] = field(default_factory=list)
    requires: Set[str] = field(default_factory=set)


@dataclass
class TaskCtx:
    """单文件并发处理任务上下文。"""

    raw_path: str
    node: FileNode
    pure_filename: str
    ext: str
    output_dir: str
    api_url: str
    model_name: str
    timeout: int
    retries: int
    no_ai: bool
    force: bool
