"""Markdown 渲染：YAML frontmatter / wiki-link 安全转义。"""

from __future__ import annotations

import re
from typing import List

from .models import FileNode

_WIKILINK_BAD = re.compile(r"[\[\]\|#\^\\/:]")


def yaml_quote(value: str) -> str:
    """生成可安全嵌入 frontmatter 的双引号字符串。"""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def safe_wiki_name(name: str) -> str:
    """Obsidian wiki-link 不允许 `[ ] | # ^ \\ / :`，统一替换为下划线。"""
    return _WIKILINK_BAD.sub("_", name)


def render_markdown(
    raw_path: str,
    pure_filename: str,
    ext: str,
    node: FileNode,
    ai_summary: str,
) -> str:
    """根据 FileNode 渲染单文件 Markdown 内容。"""
    safe_name = safe_wiki_name(pure_filename)

    lines: List[str] = []
    lines.append("---")
    lines.append(f"source_code_path: {yaml_quote(raw_path)}")
    lines.append(f"file_type: {yaml_quote(ext)}")
    lines.append(f"summary: {yaml_quote(ai_summary)}")
    lines.append('status: "hybrid_graph_node"')
    lines.append("---\n")

    lines.append(f"# 📄 {safe_name}{ext}\n")
    lines.append(f"> **💡 业务职责概括：** {ai_summary}\n")

    lines.append("### 🔗 物理引用依赖")
    deps = sorted(d for d in node.requires if d and d != pure_filename)
    if deps:
        lines.extend(f"* [[{safe_wiki_name(d)}]]" for d in deps)
    else:
        lines.append("* 无显式符号耦合")

    lines.append("\n### 🏛️ 核心类型声明")
    lines.append("\n".join(node.classes) if node.classes else "_无类声明_")

    lines.append("\n### ⚙️ 暴露的方法与函数签名")
    lines.append("\n".join(node.functions) if node.functions else "_无独立函数声明_")

    if node.members:
        lines.append("\n### 🧩 成员/字段")
        lines.append("\n".join(node.members))

    return "\n".join(lines) + "\n"
