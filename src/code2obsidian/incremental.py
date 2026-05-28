"""增量分析：基于 git diff 的变更检测、旧 md 合并、变更报告生成。

设计要点：
1. **粒度选择**：以"文件"为最小单元做 diff（A/M/D/R），不解析 hunk。
   理由：实现稳定、ctags 必须按整文件重跑、对 token 浪费极有限。
2. **旧 md 合并策略**：保留旧 frontmatter 的 `summary` 字段以及"💡 业务职责概括"段落，
   只重写「物理引用依赖 / 类型声明 / 类型别名 / 函数签名 / 成员」这些结构化小节。
   这样可以**避免每次 diff 都重新调用昂贵的 LLM**。
3. **变更报告**：单独输出一份 `_CHANGES_<a>_<b>.md`，给排 bug 的人一份"上帝视角"。
   同时每个变更文件的 md 顶部追加一个轻量的「🔥 最近变更」段落。
4. **依赖网刷新**：变更文件的反向依赖（旧 vault 里 requires 包含变更文件的那些）
   也会被重新加入待重渲列表，避免依赖网陈旧。
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .logging_utils import logger
from .models import FileNode
from .renderer import render_markdown, safe_wiki_name, yaml_quote


# ---------------------------------------------------------------- 数据结构

@dataclass
class ChangeRecord:
    """单个文件级变更。"""

    status: str            # 'A' 新增 / 'M' 修改 / 'D' 删除 / 'R' 重命名
    path: str              # 终点 commit 下的相对路径（D 时为旧路径）
    old_path: str = ""     # R 时记录原始路径
    added: int = 0         # 新增行数（git numstat）
    removed: int = 0       # 删除行数

    @property
    def basename(self) -> str:
        return os.path.splitext(os.path.basename(self.path))[0]

    @property
    def is_delete(self) -> bool:
        return self.status == "D"


@dataclass
class IncrementalPlan:
    """增量分析的执行计划。"""

    commit_a: str
    commit_b: str
    changes: List[ChangeRecord] = field(default_factory=list)
    # 反向依赖文件的"绝对路径"集合：它们没在 diff 里直接变更，但依赖网受影响
    reverse_dep_paths: Set[str] = field(default_factory=set)


# ---------------------------------------------------------------- git diff

_GIT_DIFF_NAME_STATUS_RE = re.compile(r"^([AMDR])\d*\s+(.+?)(?:\s+(.+))?$")


def _run_git(cmd: List[str], repo: str) -> str:
    """执行一条 git 命令并返回 stdout 文本。失败时抛 RuntimeError。"""
    try:
        proc = subprocess.run(
            cmd,
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
    except FileNotFoundError as e:
        raise RuntimeError("未找到 git 可执行文件，请先安装 git") from e
    if proc.returncode != 0:
        raise RuntimeError(
            f"git 命令失败 ({' '.join(cmd)}): {proc.stderr.strip()}"
        )
    return proc.stdout


def _detect_git_root(path: str) -> Optional[str]:
    """探测 path 所在的 git 仓库根。

    兼容场景：
    1. 普通仓库（``.git`` 是目录）。
    2. **git worktree**（``.git`` 是文件，内容形如 ``gitdir: /path/to/.git/worktrees/xxx``）。
    3. **submodule**（``.git`` 也是文件）。
    4. ``path`` 位于仓库的子目录中。

    实现策略：优先调用 ``git rev-parse --show-toplevel`` 让 git 自己回答，
    这是最权威也最不容易踩坑的做法；只有在 git 不可用 / 解析失败时才退回到
    "向上递归查找 .git" 的本地实现，且本地实现同时接受目录与文件形式。
    """
    abs_path = os.path.abspath(path)

    # 优先：直接问 git
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=abs_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if proc.returncode == 0:
            top = proc.stdout.strip()
            if top:
                return top
    except FileNotFoundError:
        # 系统没装 git，落回本地遍历
        pass

    # Fallback：本地向上查找，目录或文件形式的 .git 都算
    cur = abs_path
    while True:
        dot_git = os.path.join(cur, ".git")
        if os.path.isdir(dot_git) or os.path.isfile(dot_git):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def diff_files(
    source_dir: str,
    commit_a: str,
    commit_b: str,
    include_exts: Optional[Set[str]] = None,
) -> Tuple[str, List[ChangeRecord]]:
    """从 git diff 提取变更文件清单。

    Returns:
        (git_root, changes)。其中 changes 中的 path 已转换为绝对路径。
    """
    git_root = _detect_git_root(source_dir)
    if git_root is None:
        raise RuntimeError(
            f"source 目录不在 git 仓库内，无法做增量分析：{source_dir}"
        )

    # name-status 拿动作类型，numstat 拿增删行数
    name_status = _run_git(
        ["git", "diff", "--name-status", "-M", commit_a, commit_b],
        git_root,
    )
    numstat = _run_git(
        ["git", "diff", "--numstat", "-M", commit_a, commit_b],
        git_root,
    )

    # numstat: "added\tremoved\tpath" 或 "added\tremoved\told => new"（重命名）
    line_stat: Dict[str, Tuple[int, int]] = {}
    for line in numstat.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added_s, removed_s, path_s = parts[0], parts[1], parts[2]
        # 二进制文件 numstat 给 "-"
        try:
            added = int(added_s)
            removed = int(removed_s)
        except ValueError:
            added = removed = 0
        # 重命名形式 "old => new" 或 "{prefix => prefix}/path"，简单取最后一段
        if "=>" in path_s:
            # 优先解析 "{a => b}/c" 形式
            m = re.match(r"^(.*?)\{(.*?) => (.*?)\}(.*)$", path_s)
            if m:
                final = (m.group(1) + m.group(3) + m.group(4)).replace("//", "/")
            else:
                # 形如 "old => new"
                final = path_s.split("=>")[-1].strip()
            path_s = final
        line_stat[path_s] = (added, removed)

    src_abs = os.path.abspath(source_dir)
    changes: List[ChangeRecord] = []
    for line in name_status.splitlines():
        line = line.rstrip()
        if not line:
            continue
        # 形如：M\tpath  /  R100\told\tnew  /  A\tpath  /  D\tpath
        parts = line.split("\t")
        if not parts:
            continue
        head = parts[0]
        status = head[0]
        if status not in {"A", "M", "D", "R"}:
            continue
        if status == "R" and len(parts) >= 3:
            old_rel, new_rel = parts[1], parts[2]
            target_rel = new_rel
            old_path_rel = old_rel
        elif len(parts) >= 2:
            target_rel = parts[1]
            old_path_rel = ""
        else:
            continue

        # 过滤扩展名
        if include_exts:
            ext = os.path.splitext(target_rel)[1].lower()
            if ext not in include_exts:
                continue

        # 过滤是否在 source_dir 范围内
        abs_path = os.path.normpath(os.path.join(git_root, target_rel))
        if not abs_path.startswith(src_abs + os.sep) and abs_path != src_abs:
            # 用户限定的 source 是 git_root 子目录，跳过子目录之外的变更
            continue

        added, removed = line_stat.get(target_rel, (0, 0))
        changes.append(ChangeRecord(
            status=status,
            path=abs_path,
            old_path=old_path_rel,
            added=added,
            removed=removed,
        ))
    return git_root, changes


# ---------------------------------------------------------------- 旧 md 解析

# 截取出 frontmatter 中的 summary 字段（保留 LLM 旧摘要不被白白丢弃）
_SUMMARY_RE = re.compile(
    r'^summary:\s*"((?:[^"\\]|\\.)*)"\s*$',
    re.MULTILINE,
)


def _unescape_yaml_quoted(s: str) -> str:
    return s.replace('\\"', '"').replace("\\\\", "\\")


def read_old_summary(md_path: str) -> Optional[str]:
    """读取旧 md 的 LLM 摘要；不存在或解析失败返回 None。"""
    if not os.path.isfile(md_path):
        return None
    try:
        with open(md_path, "r", encoding="utf-8") as fh:
            text = fh.read(8192)  # frontmatter 一定在文件头部，截断即可
    except OSError:
        return None
    m = _SUMMARY_RE.search(text)
    if not m:
        return None
    return _unescape_yaml_quoted(m.group(1))


# ---------------------------------------------------------------- md 合并

def render_markdown_with_change(
    raw_path: str,
    pure_filename: str,
    ext: str,
    node: FileNode,
    ai_summary: str,
    change: Optional[ChangeRecord],
    commit_a: str,
    commit_b: str,
) -> str:
    """在 render_markdown 输出之上，于"业务职责概括"后插入一段🔥 最近变更。"""
    base = render_markdown(raw_path, pure_filename, ext, node, ai_summary)
    if change is None:
        return base

    badge_map = {"A": "🆕 新增", "M": "✏️ 修改", "R": "🔀 重命名"}
    badge = badge_map.get(change.status, "📝 变更")
    short_a, short_b = commit_a[:7], commit_b[:7]
    lines = [
        "",
        "### 🔥 最近变更",
        f"- 状态：{badge}",
        f"- 区间：`{short_a}` → `{short_b}`",
        f"- 行数：+{change.added} / -{change.removed}",
    ]
    if change.status == "R" and change.old_path:
        lines.append(f"- 原路径：`{change.old_path}`")
    block = "\n".join(lines) + "\n"

    # 在第一个 "### 🔗 物理引用依赖" 标题前插入
    marker = "### 🔗 物理引用依赖"
    idx = base.find(marker)
    if idx < 0:
        # 异常兜底：直接追加
        return base + block
    return base[:idx] + block + "\n" + base[idx:]


# ---------------------------------------------------------------- 反向依赖

def reverse_deps_of(
    vault_dir: str,
    changed_basenames: Set[str],
) -> Set[str]:
    """扫描 vault 目录里所有 md，找出 requires 包含 changed_basenames 的文件。

    返回这些文件对应的"源码绝对路径"集合（从 frontmatter 的 source_code_path 取）。
    用 grep 风格的轻量正则即可，不需要全量解析。
    """
    if not changed_basenames or not os.path.isdir(vault_dir):
        return set()

    # frontmatter 的 source_code_path 字段
    src_re = re.compile(
        r'^source_code_path:\s*"((?:[^"\\]|\\.)*)"\s*$',
        re.MULTILINE,
    )
    # wiki link 引用形如 * [[basename]]
    wiki_re = re.compile(r"\*\s*\[\[([^\]]+)\]\]")

    affected_paths: Set[str] = set()
    for fname in os.listdir(vault_dir):
        if not fname.endswith(".md"):
            continue
        # 跳过自己生成的变更报告
        if fname.startswith("_CHANGES_"):
            continue
        full = os.path.join(vault_dir, fname)
        try:
            with open(full, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        deps = {safe_wiki_name(d) for d in wiki_re.findall(text)}
        # 注意 changed_basenames 也要走 safe_wiki_name 一致化
        normalized_changed = {safe_wiki_name(b) for b in changed_basenames}
        if not deps & normalized_changed:
            continue
        m = src_re.search(text)
        if m:
            affected_paths.add(_unescape_yaml_quoted(m.group(1)))
    return affected_paths


# ---------------------------------------------------------------- 变更报告

def render_changes_report(
    commit_a: str,
    commit_b: str,
    changes: List[ChangeRecord],
    file_vault: Dict[str, FileNode],
    vault_dir: str,
    reverse_paths: Set[str],
) -> str:
    """生成跨文件的"变更总览报告"md 内容。

    file_vault 来自最新 ctags 扫描，能拿到每个变更文件最新的依赖与符号。
    """
    short_a, short_b = commit_a[:7], commit_b[:7]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    by_status: Dict[str, List[ChangeRecord]] = {"A": [], "M": [], "D": [], "R": []}
    for c in changes:
        by_status.setdefault(c.status, []).append(c)

    lines: List[str] = []
    lines.append("---")
    lines.append(f'kind: "code2obsidian_changes_report"')
    lines.append(f"commit_from: {yaml_quote(commit_a)}")
    lines.append(f"commit_to: {yaml_quote(commit_b)}")
    lines.append(f"generated_at: {yaml_quote(now)}")
    lines.append("---\n")

    lines.append(f"# 🔄 变更报告: `{short_a}` → `{short_b}`\n")
    lines.append(
        f"> 生成时间：{now}　|　修改 {len(by_status['M'])}　|　"
        f"新增 {len(by_status['A'])}　|　删除 {len(by_status['D'])}　|　"
        f"重命名 {len(by_status['R'])}　|　反向依赖刷新 {len(reverse_paths)}\n"
    )

    def _section(title: str, items: List[ChangeRecord]) -> None:
        if not items:
            return
        lines.append(f"## {title}")
        for c in sorted(items, key=lambda x: x.path):
            base = c.basename
            link = f"[[{safe_wiki_name(base)}]]"
            stat = f"+{c.added}/-{c.removed}"
            row = f"### {link}  `{stat}`"
            lines.append(row)
            if c.status == "R" and c.old_path:
                lines.append(f"- 原路径: `{c.old_path}`")
            node = file_vault.get(c.path)
            if node is None and c.status != "D":
                lines.append("- _（ctags 未识别到符号；可能是资源文件）_")
            elif node is not None:
                # 简明列出：类/类型/函数 数量 + 依赖列表
                cls_n = len(node.classes)
                fn_n = len(node.functions)
                ty_n = len(node.types)
                mem_n = len(node.members)
                lines.append(
                    f"- 符号: 类 {cls_n} / 函数 {fn_n} / 类型 {ty_n} / 字段 {mem_n}"
                )
                deps = sorted(d for d in node.requires if d and d != base)
                if deps:
                    dep_links = ", ".join(f"[[{safe_wiki_name(d)}]]" for d in deps)
                    lines.append(f"- 依赖: {dep_links}")
                else:
                    lines.append("- 依赖: _无_")
            lines.append("")
        lines.append("")

    _section("✏️ 修改的文件", by_status["M"])
    _section("🆕 新增的文件", by_status["A"])
    _section("🔀 重命名的文件", by_status["R"])

    if by_status["D"]:
        lines.append("## 🗑️ 删除的文件")
        for c in sorted(by_status["D"], key=lambda x: x.path):
            lines.append(f"- `{os.path.basename(c.path)}`  +{c.added}/-{c.removed}")
        lines.append("")

    if reverse_paths:
        lines.append("## 🔁 反向依赖刷新")
        lines.append("> 这些文件本身未在 diff 内，但所依赖的符号发生了变化，已重新生成 md。\n")
        for p in sorted(reverse_paths):
            base = os.path.splitext(os.path.basename(p))[0]
            lines.append(f"- [[{safe_wiki_name(base)}]]  `{p}`")
        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 删除处理

def handle_deletions(
    deletions: Iterable[ChangeRecord],
    vault_dir: str,
) -> List[str]:
    """物理删除 vault 里对应的 md。返回被删除文件的 basename 列表。"""
    removed: List[str] = []
    for c in deletions:
        base = c.basename
        md_name = f"{safe_wiki_name(base)}.md"
        md_path = os.path.join(vault_dir, md_name)
        if os.path.isfile(md_path):
            try:
                os.remove(md_path)
                removed.append(base)
                logger.info("🗑️ 已删除旧文档: %s", md_name)
            except OSError as e:
                logger.warning("⚠️ 删除失败 %s: %s", md_path, e)
    return removed
