"""incremental 模块单元测试：聚焦不需要真实 git 仓库就能验证的纯函数。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from code2obsidian.incremental import (  # noqa: E402
    ChangeRecord,
    handle_deletions,
    read_old_summary,
    render_changes_report,
    render_markdown_with_change,
    reverse_deps_of,
)
from code2obsidian.models import FileNode  # noqa: E402
from code2obsidian.renderer import render_markdown  # noqa: E402


def test_read_old_summary_extracts_quoted_value():
    with tempfile.TemporaryDirectory() as tmp:
        md = os.path.join(tmp, "foo.md")
        node = FileNode(classes=["- `class Foo` (Line 1)"])
        with open(md, "w", encoding="utf-8") as fh:
            fh.write(render_markdown("/abs/foo.py", "foo", ".py", node, '历史"摘要"'))
        # 应当能反解出含转义引号的旧 summary
        assert read_old_summary(md) == '历史"摘要"'


def test_read_old_summary_returns_none_for_missing_file():
    assert read_old_summary("/nonexistent/path.md") is None


def test_render_markdown_with_change_inserts_block_before_deps():
    node = FileNode(classes=["- `class Foo` (Line 1)"])
    change = ChangeRecord(status="M", path="/abs/foo.py", added=10, removed=3)
    md = render_markdown_with_change(
        "/abs/foo.py", "foo", ".py", node, "AI 摘要",
        change, "abc1234", "def5678",
    )
    # 顺序：变更块在 物理引用依赖 之前
    idx_change = md.find("### 🔥 最近变更")
    idx_deps = md.find("### 🔗 物理引用依赖")
    assert idx_change > 0 and idx_deps > 0
    assert idx_change < idx_deps
    # 区间和行数都应当出现
    assert "abc1234" in md and "def5678" in md
    assert "+10 / -3" in md
    assert "✏️ 修改" in md


def test_render_markdown_with_change_none_falls_back():
    """change=None 时输出应当与原始 render_markdown 完全一致。"""
    node = FileNode(classes=["- `class Foo` (Line 1)"])
    md1 = render_markdown_with_change(
        "/abs/foo.py", "foo", ".py", node, "x", None, "a", "b",
    )
    md2 = render_markdown("/abs/foo.py", "foo", ".py", node, "x")
    assert md1 == md2


def test_reverse_deps_of_finds_dependents():
    """A 改了，B 的 vault md 里有 [[A]]，那么 B 应该被加入反向依赖刷新。"""
    with tempfile.TemporaryDirectory() as tmp:
        # B.md 依赖 A
        node_b = FileNode(requires={"A"})
        b_md = render_markdown("/repo/B.py", "B", ".py", node_b, "B 摘要")
        with open(os.path.join(tmp, "B.md"), "w", encoding="utf-8") as fh:
            fh.write(b_md)
        # C.md 与 A 无关
        node_c = FileNode(classes=["- `class C` (Line 1)"])
        c_md = render_markdown("/repo/C.py", "C", ".py", node_c, "C 摘要")
        with open(os.path.join(tmp, "C.md"), "w", encoding="utf-8") as fh:
            fh.write(c_md)

        affected = reverse_deps_of(tmp, {"A"})
        assert affected == {"/repo/B.py"}


def test_handle_deletions_removes_files():
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "foo.md")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("placeholder")
        deletions = [ChangeRecord(status="D", path="/repo/foo.py")]
        removed = handle_deletions(deletions, tmp)
        assert "foo" in removed
        assert not os.path.exists(target)


def test_handle_deletions_silently_skips_missing():
    with tempfile.TemporaryDirectory() as tmp:
        deletions = [ChangeRecord(status="D", path="/repo/ghost.py")]
        removed = handle_deletions(deletions, tmp)
        assert removed == []


def test_render_changes_report_groups_by_status():
    changes = [
        ChangeRecord(status="M", path="/repo/a.py", added=5, removed=1),
        ChangeRecord(status="A", path="/repo/b.py", added=20, removed=0),
        ChangeRecord(status="D", path="/repo/c.py"),
        ChangeRecord(status="R", path="/repo/d2.py", old_path="repo/d1.py"),
    ]
    file_vault = {
        "/repo/a.py": FileNode(
            classes=["- `class A` (Line 1)"], requires={"b"},
        ),
        "/repo/b.py": FileNode(classes=["- `class B` (Line 1)"]),
        "/repo/d2.py": FileNode(),
    }
    md = render_changes_report(
        "abc1234", "def5678", changes, file_vault,
        "/some/vault", set(),
    )
    # 标题
    assert "🔄 变更报告" in md
    # 各分类
    assert "✏️ 修改的文件" in md
    assert "🆕 新增的文件" in md
    assert "🗑️ 删除的文件" in md
    assert "🔀 重命名的文件" in md
    # wiki 链接
    assert "[[a]]" in md and "[[b]]" in md
    # 行数
    assert "+5/-1" in md
    # 重命名要带原路径
    assert "repo/d1.py" in md
    # 依赖列表
    assert "依赖: [[b]]" in md


def test_change_record_basename_strips_ext():
    c = ChangeRecord(status="M", path="/x/y/foo.bar.ts")
    assert c.basename == "foo.bar"
