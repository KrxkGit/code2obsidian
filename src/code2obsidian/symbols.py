"""符号网构建：单次遍历 ctags 输出，建立全局符号表与文件节点。"""

from __future__ import annotations

import os
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .models import FileNode

CLASS_KINDS = {"class", "struct", "interface", "enum", "typedef", "protocol"}
FUNC_KINDS = {"function", "method"}
MEMBER_KINDS = {"member", "field", "property", "variable"}

_IDENT_RE = re.compile(r"^[A-Za-z_]\w*$")


def collect_symbols(
    tags: Iterable[dict],
    include_exts: Optional[Set[str]] = None,
) -> Tuple[Dict[str, FileNode], Dict[str, Set[str]]]:
    """
    从 ctags 流中聚合每个文件的符号信息，并构建跨文件的依赖关系。

    使用「单词边界正则」精准匹配，避免 `User → UserService` 之类的子串误判。
    返回 (file_vault, global_symbol_map)。
    """
    file_vault: Dict[str, FileNode] = {}
    # name -> 拥有该符号的所有文件 basename（处理重名）
    global_symbol_map: Dict[str, Set[str]] = {}
    # 第一次扫描时暂存的待解析依赖文本：(path, text)
    pending_refs: List[Tuple[str, str]] = []

    for tag in tags:
        path = tag.get("path")
        if not path:
            continue
        if include_exts:
            ext = os.path.splitext(path)[1].lower()
            if ext not in include_exts:
                continue

        name = tag.get("name") or ""
        kind = tag.get("kind") or ""
        line = tag.get("line", "?")
        typ = tag.get("type", "") or ""
        signature = tag.get("signature", "") or ""
        inherits = tag.get("inherits", "") or ""

        node = file_vault.setdefault(path, FileNode())
        base_name = os.path.splitext(os.path.basename(path))[0]

        if kind in CLASS_KINDS and name:
            node.classes.append(f"- `{kind} {name}` (Line {line})")
            global_symbol_map.setdefault(name, set()).add(base_name)
        elif kind in FUNC_KINDS and name:
            sig = signature if signature else "()"
            ret = f" [Returns: {typ}]" if typ else ""
            node.functions.append(f"- `{name}{sig}`{ret} (Line {line})")
        elif kind in MEMBER_KINDS and name:
            t = f": {typ}" if typ else ""
            node.members.append(f"- `{name}{t}` (Line {line})")

        # 暂存所有可能引用其它类型的文本
        ref_text = " ".join(filter(None, [signature, inherits, typ]))
        if ref_text:
            pending_refs.append((path, ref_text))

    _resolve_dependencies(file_vault, global_symbol_map, pending_refs)
    return file_vault, global_symbol_map


def _resolve_dependencies(
    file_vault: Dict[str, FileNode],
    global_symbol_map: Dict[str, Set[str]],
    pending_refs: List[Tuple[str, str]],
) -> None:
    """二次扫描，使用单词边界正则一次性匹配所有已知符号。"""
    if not global_symbol_map:
        return

    # 按长度倒序确保 "UserService" 优先于 "User" 匹配
    sorted_syms = sorted(global_symbol_map.keys(), key=len, reverse=True)
    sorted_syms = [s for s in sorted_syms if len(s) >= 2 and _IDENT_RE.match(s)]
    if not sorted_syms:
        return

    big_re = re.compile(r"\b(" + "|".join(map(re.escape, sorted_syms)) + r")\b")

    for path, text in pending_refs:
        node = file_vault.get(path)
        if not node:
            continue
        self_base = os.path.splitext(os.path.basename(path))[0]
        for hit in big_re.findall(text):
            for target in global_symbol_map.get(hit, ()):
                if target != self_base:
                    node.requires.add(target)
