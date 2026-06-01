"""lang_map 相关：ctags 参数拼装 + CLI 字符串解析。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from code2obsidian.ctags import (  # noqa: E402
    _augment_lang_map_with_builtin_exts,
    _build_langmap_args,
    _resolve_builtin_options,
    _BUILTIN_LANG_RULES,
    _RESOURCES_DIR,
)
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


# ---------------------------------------------------------------------------
# 内建语言规则（如 Dart）：lang_map 命中后自动注入 --options=<file>
# ---------------------------------------------------------------------------
def test_builtin_dart_rule_file_shipped():
    """随包分发的 dart.ctags 必须存在，否则下游注入时会 warning 退化。"""
    rule_path = Path(_RESOURCES_DIR) / _BUILTIN_LANG_RULES["dart"]
    assert rule_path.is_file(), f"missing builtin rule: {rule_path}"


def test_resolve_builtin_options_for_dart():
    args = _resolve_builtin_options({".dart": "Dart"})
    assert len(args) == 1
    assert args[0].startswith("--options=")
    # 路径指向真实存在的规则文件
    rule_path = args[0].split("=", 1)[1]
    assert Path(rule_path).is_file()


def test_resolve_builtin_options_dedup_same_lang():
    """多扩展名映射到同一语言时只注入一次。"""
    args = _resolve_builtin_options({".dart": "Dart", ".dart2": "dart"})
    assert len(args) == 1


def test_resolve_builtin_options_no_match():
    """非内建语言不应注入任何 options。"""
    assert _resolve_builtin_options({".ets": "TypeScript"}) == []
    assert _resolve_builtin_options(None) == []
    assert _resolve_builtin_options({}) == []


def test_augment_lang_map_with_builtin_dart_include_ext():
    """只配置 include_ext=.dart 时，也应自动启用 Dart 内建规则。"""
    assert _augment_lang_map_with_builtin_exts({}, {".dart"}) == {".dart": "Dart"}


def test_augment_lang_map_with_builtin_ets_include_ext():
    """只配置 include_ext=.ets 时，也应自动启用 ArkTS 内建规则。"""
    assert _augment_lang_map_with_builtin_exts({}, {".ets"}) == {".ets": "ArkTS"}


def test_augment_lang_map_with_builtin_multi_include_exts():
    assert _augment_lang_map_with_builtin_exts({}, {".dart", ".ets"}) == {
        ".dart": "Dart",
        ".ets": "ArkTS",
    }


def test_augment_lang_map_keeps_explicit_mapping():
    """显式 lang_map 优先，自动补全不能覆盖用户配置。"""
    assert _augment_lang_map_with_builtin_exts({".dart": "TypeScript"}, {".dart"}) == {
        ".dart": "TypeScript",
    }
    assert _augment_lang_map_with_builtin_exts({".ets": "JavaScript"}, {".ets"}) == {
        ".ets": "JavaScript",
    }


def test_augment_lang_map_ignores_unknown_include_ext():
    assert _augment_lang_map_with_builtin_exts({}, {".py"}) == {}


def test_builtin_arkts_rule_file_shipped():
    """随包分发的 arkts.ctags 必须存在，否则 .ets 会退化。"""
    rule_path = Path(_RESOURCES_DIR) / _BUILTIN_LANG_RULES["arkts"]
    assert rule_path.is_file(), f"missing builtin rule: {rule_path}"


def test_resolve_builtin_options_for_arkts():
    args = _resolve_builtin_options({".ets": "ArkTS"})
    assert len(args) == 1
    assert args[0].startswith("--options=")
    rule_path = args[0].split("=", 1)[1]
    assert Path(rule_path).is_file()
