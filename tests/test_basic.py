"""renderer / symbols 的轻量单元测试，无外部依赖。"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许在未安装时直接跑 pytest
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from code2obsidian.models import FileNode  # noqa: E402
from code2obsidian.renderer import (  # noqa: E402
    render_markdown,
    safe_wiki_name,
    yaml_quote,
)
from code2obsidian.symbols import collect_symbols  # noqa: E402


def test_yaml_quote_escapes_quotes_and_backslash():
    assert yaml_quote('a"b') == '"a\\"b"'
    assert yaml_quote("a\\b") == '"a\\\\b"'


def test_safe_wiki_name_replaces_forbidden_chars():
    assert safe_wiki_name("a[b]c#d") == "a_b_c_d"
    assert safe_wiki_name("normal_name") == "normal_name"


def test_render_markdown_minimal():
    node = FileNode(
        classes=["- `class Foo` (Line 1)"],
        functions=["- `bar()` (Line 2)"],
    )
    md = render_markdown("/abs/foo.py", "foo", ".py", node, "做 Foo 相关的事")
    assert "summary: \"做 Foo 相关的事\"" in md
    assert "# 📄 foo.py" in md
    assert "无显式符号耦合" in md


def test_collect_symbols_precise_word_boundary():
    """User 不应该被误识别为 UserService 的依赖。"""
    tags = [
        {"path": "/p/User.py", "name": "User", "kind": "class", "line": 1},
        {"path": "/p/UserService.py", "name": "UserService", "kind": "class",
         "line": 1, "inherits": "BaseService"},
        # service 文件内部有一个使用 User 的方法签名
        {"path": "/p/UserService.py", "name": "save", "kind": "method",
         "line": 5, "signature": "(self, u: User)"},
    ]
    vault, sym_map = collect_symbols(iter(tags))
    assert "User" in sym_map and "UserService" in sym_map
    # UserService.py 应当依赖 User
    assert "User" in vault["/p/UserService.py"].requires
    # User.py 不应该自指
    assert "User" not in vault["/p/User.py"].requires


def test_collect_symbols_dedup_same_name_in_multiple_files():
    tags = [
        {"path": "/a/Logger.py", "name": "Logger", "kind": "class", "line": 1},
        {"path": "/b/Logger.py", "name": "Logger", "kind": "class", "line": 1},
    ]
    _, sym_map = collect_symbols(iter(tags))
    assert sym_map["Logger"] == {"Logger"}  # 都映射到同一 basename
