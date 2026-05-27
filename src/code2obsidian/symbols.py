"""符号网构建：单次遍历 ctags 输出，建立全局符号表与文件节点。"""

from __future__ import annotations

import os
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .models import FileNode

CLASS_KINDS = {"class", "struct", "interface", "enum", "typedef", "protocol"}
FUNC_KINDS = {"function", "method"}
MEMBER_KINDS = {"member", "field", "property", "variable"}
# ts/ets/python 的"类型层"声明：type alias、namespace、module 等
# 收进来主要有两个目的：
#   1) 让它们的名字进入 global_symbol_map，方便 signature 撞库时匹配到
#      （否则 `(cb: Callback<User>)` 里的 Callback 永远连不上）
#   2) 在最终 md 里以"类型声明"小节形式呈现，让 ts/ets 文件不再几乎空白
ALIAS_KINDS = {"alias", "typealias"}
NAMESPACE_KINDS = {"namespace", "module", "package"}

_IDENT_RE = re.compile(r"^[A-Za-z_]\w*$")
# ctags 的 pattern 形如 "/^  async getUser(id: UserId): Promise<User> { ... }$/"
# 这是唯一在 TypeScript 等"弱字段"语言里**稳定包含原始声明行**的字段。
# 我们把它去掉外壳后纳入依赖匹配文本，最大化压榨 ctags 视野下的信息。
_PATTERN_WRAP_RE = re.compile(r'^/\^?(.*?)\$?/$', re.S)


def _strip_pattern(pattern: str) -> str:
    """剥掉 ctags pattern 的 /^...$/ 包裹，并做最基础的转义反解。"""
    if not pattern:
        return ""
    m = _PATTERN_WRAP_RE.match(pattern)
    body = m.group(1) if m else pattern
    # ctags 会把 / 反斜杠转义，这里反向还原即可
    return body.replace("\\/", "/").replace("\\\\", "\\")


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
        scope = tag.get("scope", "") or ""
        pattern_text = _strip_pattern(tag.get("pattern", "") or "")

        node = file_vault.setdefault(path, FileNode())
        base_name = os.path.splitext(os.path.basename(path))[0]

        if kind in CLASS_KINDS and name:
            node.classes.append(f"- `{kind} {name}` (Line {line})")
            global_symbol_map.setdefault(name, set()).add(base_name)
        elif kind in FUNC_KINDS and name:
            # 优先使用 ctags 给的 signature；没有时（如 ts）退化为 pattern 文本
            # 至少能在 md 里看到原始声明行，对用户也更直观
            if signature:
                display = f"{name}{signature}"
            elif pattern_text:
                display = pattern_text.strip()
            else:
                display = f"{name}()"
            ret = f" [Returns: {typ}]" if typ else ""
            node.functions.append(f"- `{display}`{ret} (Line {line})")
        elif kind in ALIAS_KINDS and name:
            # `type Foo = ...` / `import xxx as Foo` 之类
            node.types.append(f"- `alias {name}` (Line {line})")
            global_symbol_map.setdefault(name, set()).add(base_name)
        elif kind in NAMESPACE_KINDS and name:
            node.types.append(f"- `{kind} {name}` (Line {line})")
            global_symbol_map.setdefault(name, set()).add(base_name)
        elif kind in MEMBER_KINDS and name:
            t = f": {typ}" if typ else ""
            node.members.append(f"- `{name}{t}` (Line {line})")

        # 暂存所有可能引用其它类型的文本
        # 把 scope 与 pattern 都纳入：
        #   - scope 体现归属（class Inner scope=MyNs）
        #   - pattern 是 ts 等语言下唯一可靠的"原始声明行"，承载参数/返回/extends 等真实依赖
        ref_text = " ".join(filter(None, [signature, inherits, typ, scope, pattern_text]))
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
