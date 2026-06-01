"""配置文件加载：支持 TOML，提供命令行参数 ↔ 配置文件的合并策略。

加载优先级（从高到低）：
    1. 命令行**显式**指定的参数（即使值与默认值相同也算显式）
    2. 配置文件
    3. argparse 的默认值

支持的查找路径：
    - --config <path> 显式指定
    - 当前工作目录 ./code2obsidian.toml
    - <source>/code2obsidian.toml
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, Optional

from .logging_utils import logger

# argparse 选项名（中划线）→ TOML key（下划线）的标准化函数
def _norm(key: str) -> str:
    return key.strip().replace("-", "_").lower()


# 允许出现在配置文件中的字段白名单，避免拼写错误被静默吞掉
ALLOWED_KEYS = {
    "source", "output", "model", "url", "threads", "timeout",
    "retries", "include_ext", "no_ai", "force", "verbose",
    "lang_map",  # dict[str, str]: 扩展名 → ctags 语言名，如 {".ets": "ArkTS"}
}


def _load_toml(path: str) -> Dict[str, Any]:
    """优先标准库 tomllib（3.11+）→ tomli → 内置 mini 解析器（保证零依赖可用）。"""
    try:
        import tomllib  # type: ignore[attr-defined]
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except ImportError:
        pass
    try:
        import tomli  # type: ignore
        with open(path, "rb") as fh:
            return tomli.load(fh)
    except ImportError:
        pass

    logger.debug("使用内置 mini TOML 解析器读取 %s（建议升级 Python 3.11+ 获得完整支持）", path)
    with open(path, "r", encoding="utf-8") as fh:
        return _mini_toml_parse(fh.read())


def _mini_toml_parse(text: str) -> Dict[str, Any]:
    """
    极简 TOML 子集解析器，仅支持 code2obsidian 配置所需特性：
      - `# 注释`、空行
      - `[section]` / `[a.b]` 嵌套段
      - `key = value`，value 支持: "字符串" / 'string' / 整数 / 浮点 / true / false
      - 数组与多行字符串等高级语法**不**支持（也用不到）
    """
    root: Dict[str, Any] = {}
    cur: Dict[str, Any] = root

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            path_parts = [p.strip() for p in line[1:-1].split(".") if p.strip()]
            cur = root
            for part in path_parts:
                cur = cur.setdefault(part, {})
                if not isinstance(cur, dict):
                    raise ValueError(f"TOML 段 [{line[1:-1]}] 与已有标量冲突")
            continue
        if "=" not in line:
            raise ValueError(f"无法解析 TOML 行: {raw_line!r}")
        key, _, val = line.partition("=")
        key = key.strip()
        # 支持带引号的 key（如 ".ets" = "TypeScript"），mini 子集
        if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
            key = key[1:-1]
        # 去掉行内注释（仅在不是字符串内部时；mini 实现采用近似策略）
        val = val.strip()
        if val and val[0] not in ("\"", "'"):
            hash_pos = val.find("#")
            if hash_pos >= 0:
                val = val[:hash_pos].strip()
        cur[key] = _mini_toml_value(val)
    return root


def _mini_toml_value(raw: str) -> Any:
    s = raw.strip()
    if not s:
        return ""
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        body = s[1:-1]
        # 仅处理基本的转义
        return body.replace('\\"', '"').replace("\\\\", "\\")
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    # 数值
    try:
        if any(ch in s for ch in (".", "e", "E")):
            return float(s)
        return int(s)
    except ValueError:
        return s  # 兜底当字符串


def _flatten(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    把 toml 解析结果展开成扁平 dict。
    既支持顶层 `threads = 16`，也支持 [code2obsidian] / [tool.code2obsidian] 嵌套。
    例外：`lang_map` 需要保留为 dict（可能写成 [code2obsidian.lang_map] 子表）。
    """
    flat: Dict[str, Any] = {}

    def _absorb(section: Dict[str, Any]) -> None:
        for k, v in section.items():
            nk = _norm(k)
            if nk == "lang_map" and isinstance(v, dict):
                flat[nk] = {str(kk): str(vv) for kk, vv in v.items()}
            elif not isinstance(v, dict):
                flat[nk] = v

    # 1) 顶层
    _absorb(data)
    # 2) 已知 section（优先级递增覆盖：顶层 < code2obsidian < tool.code2obsidian）
    for section_path in (("code2obsidian",), ("tool", "code2obsidian")):
        cur: Any = data
        for part in section_path:
            if not isinstance(cur, dict) or part not in cur:
                cur = None
                break
            cur = cur[part]
        if isinstance(cur, dict):
            _absorb(cur)
    return flat


def find_config_path(
    explicit: Optional[str],
    source_dir: Optional[str],
    cwd_candidates: Iterable[str] = ("code2obsidian.toml",),
) -> Optional[str]:
    """按既定顺序定位配置文件，找不到返回 None。"""
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        logger.warning("⚠️ --config 指定的文件不存在: %s", explicit)
        return None
    for name in cwd_candidates:
        if os.path.isfile(name):
            return os.path.abspath(name)
    if source_dir:
        candidate = os.path.join(source_dir, "code2obsidian.toml")
        if os.path.isfile(candidate):
            return candidate
    return None


def load_config(path: str) -> Dict[str, Any]:
    """读取 + 校验 + 标准化键名，返回扁平 dict。未知键给出 warning。"""
    raw = _load_toml(path)
    flat = _flatten(raw)
    cleaned: Dict[str, Any] = {}
    for k, v in flat.items():
        if k in ALLOWED_KEYS:
            cleaned[k] = v
        else:
            logger.warning("⚠️ 配置文件未知字段已忽略: %s", k)
    if cleaned:
        logger.info("📄 已加载配置 %s（%d 项）", path, len(cleaned))
    return cleaned


SAMPLE_TOML = """\
# code2obsidian 配置文件示例
# 命令行参数会覆盖此处的值；将所有字段写在 [code2obsidian] 段或顶层都可以。

[code2obsidian]
# 源码目录
source = "./src"

# Obsidian 输出目录（建议绝对路径）
# output = "/Users/you/Vault/CodeWiki"

# 本地 Ollama
model = "qwen3:8b"
url   = "http://localhost:11434/api/generate"

# 并发与重试
threads = 8
timeout = 30
retries = 2

# 仅处理指定扩展名（逗号分隔），留空表示全部
include_ext = ""

# 行为开关
no_ai   = false
force   = false
verbose = false

# 将某些扩展名“视为”某种语言让 ctags 解析（如 .ets 使用内建 ArkTS 规则）。
# key 为扩展名（包含点号），value 为 ctags 语言名；可用 `ctags --list-languages` 查看完整列表。
#
# 对于常见内建扩展名（目前：.ets -> ArkTS、.dart -> Dart），只配置
# include_ext 也会自动启用对应解析规则；显式 lang_map 仍然优先。
# ArkTS / Dart 都会自动加载随包分发的 ctags 规则文件，无需你额外配置。
[code2obsidian.lang_map]
# ".ets" = "ArkTS"     # 可省略：include_ext = ".ets" 时会自动加载 resources/arkts.ctags
# ".mts" = "TypeScript"
# ".cts" = "TypeScript"
# ".dart" = "Dart"    # 可省略：include_ext = ".dart" 时会自动加载 resources/dart.ctags
"""
