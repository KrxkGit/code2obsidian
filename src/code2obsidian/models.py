"""核心数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Set


@dataclass
class FileNode:
    """单个源码文件聚合后的符号信息。"""

    classes: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    members: List[str] = field(default_factory=list)
    # type alias / namespace / typedef 等"类型层"声明，用于 ts/ets 等语言的弱类型符号
    types: List[str] = field(default_factory=list)
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
    # ---- 增量分析相关（普通模式下保持默认值，不影响行为）----
    # 增量模式：复用旧 md 的 LLM 摘要，避免每次 diff 都重跑昂贵的模型
    reuse_old_summary: bool = False
    # 该文件在 git diff 中的变更记录（None 表示反向依赖文件，不在 diff 内）
    change: Optional[Any] = None  # 实际类型 ChangeRecord，避免循环依赖此处用 Any
    commit_a: str = ""
    commit_b: str = ""
