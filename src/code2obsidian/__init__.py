"""
Code2Obsidian
=============
基于 Universal Ctags 的 100% 确定性符号扫描，结合本地 Ollama 并发语义摘要，
将任意代码库一键织成 Obsidian 知识图谱。
"""

from .models import FileNode, TaskCtx

__version__ = "0.2.0"
__all__ = ["FileNode", "TaskCtx", "__version__"]
