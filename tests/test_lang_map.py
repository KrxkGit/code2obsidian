"""lang_map 相关：ctags 参数拼装 + CLI 字符串解析。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from code2obsidian.ctags import _build_langmap_args  # noqa: E402
from code2obsidian.cli import _parse_lang_map_cli, _normalize_lang_map  # noqa: E402


def test_build_langmap_args_basic():
    args = _build_langmap_args({".ets": "TypeScript"})
    assert args == ["--map-TypeScript=+.ets"]


def test_build_langmap_args_multi_lang_and_dot_normalize():
    args = _build_langmap_args({"ets": "TypeScript", ".vue": "JavaScript"})
    # 自动补点号
    assert "--map-TypeScript=+.ets" in args
    assert "--map-JavaScript=+.vue" in args
    assert len(args) == 2


def test_build_langmap_args_empty():
    assert _build_langmap_args(None) == []
    assert _build_langmap_args({}) == []


def test_parse_lang_map_cli_string():
    m = _parse_lang_map_cli(".ets=TypeScript,.mts=TypeScript, =empty , bad")
    assert m == {".ets": "TypeScript", ".mts": "TypeScript"}


def test_normalize_lang_map_dict_passthrough():
    m = _normalize_lang_map({"ETS": "TypeScript"})
    # key 标准化为小写并补点
    assert m == {".ets": "TypeScript"}


def test_normalize_lang_map_string_passthrough():
    m = _normalize_lang_map(".ets=TypeScript")
    assert m == {".ets": "TypeScript"}
