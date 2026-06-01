"""Universal Ctags 流式扫描封装。"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Dict, Iterable, List, Optional, Set

from .logging_utils import logger

# ---------------------------------------------------------------------------
# 内建语言规则：value 是该语言对应的 *.ctags 配置文件名（与 resources/ 同目录）
#
# 设计原则：
#   - ctags 原生不支持的语言（如 Dart），通过 `--options=<file>` 注入用户级
#     `--langdef`/`--regex-XXX` 规则，避免污染用户全局配置。
#   - 仅当 lang_map 中真的出现该语言时才注入，零侵入。
#   - kind 名必须与 symbols.py 的 CLASS_KINDS / FUNC_KINDS / MEMBER_KINDS /
#     ALIAS_KINDS / NAMESPACE_KINDS 对齐，确保依赖解析与渲染零修改可复用。
# ---------------------------------------------------------------------------
_BUILTIN_LANG_RULES: Dict[str, str] = {
    "dart": "dart.ctags",
}

# 内建语言对应的默认扩展名。用于把 `--include-ext .dart` 这种仅过滤扩展名的
# 调用方式自动补全成 lang_map，避免用户还要额外记一遍 `--lang-map .dart=Dart`。
_BUILTIN_EXT_LANGS: Dict[str, str] = {
    ".dart": "Dart",
}

_RESOURCES_DIR = os.path.join(os.path.dirname(__file__), "resources")


def _augment_lang_map_with_builtin_exts(
    lang_map: Optional[Dict[str, str]],
    include_exts: Optional[Set[str]],
) -> Dict[str, str]:
    """根据 include_ext 中的内建扩展名自动补全 lang_map。"""
    out: Dict[str, str] = dict(lang_map or {})
    if not include_exts:
        return out
    for ext in sorted(include_exts):
        key = ext if ext.startswith(".") else f".{ext}"
        key = key.lower()
        if key in out:
            continue
        lang = _BUILTIN_EXT_LANGS.get(key)
        if not lang:
            continue
        out[key] = lang
        logger.info("🔗 include_ext 自动启用内建语言规则: %s ⇐ %s", lang, key)
    return out


def _resolve_builtin_options(lang_map: Optional[Dict[str, str]]) -> List[str]:
    """
    扫描 lang_map 中出现的语言，若命中内建规则则返回对应的 `--options=<path>` 参数。

    多个扩展名映射到同一语言时只注入一次；找不到规则文件会给出 warning 但不致命。
    """
    if not lang_map:
        return []
    seen: Set[str] = set()
    args: List[str] = []
    for lang in lang_map.values():
        key = (lang or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        rel = _BUILTIN_LANG_RULES.get(key)
        if not rel:
            continue
        path = os.path.join(_RESOURCES_DIR, rel)
        if not os.path.isfile(path):
            logger.warning("⚠️ 内建 ctags 规则缺失，将退化为 ctags 默认行为: %s", path)
            continue
        args.append(f"--options={path}")
        logger.info("📦 已加载内建 ctags 规则: %s ⇐ %s", lang, path)
    return args


def _build_langmap_args(lang_map: Optional[Dict[str, str]]) -> List[str]:
    """
    把 {".ets": "TypeScript"} 翻译为 ctags 命令行参数列表。

    使用 `--map-<LANG>=+.ext` 形式（增量添加，不破坏原有映射）。
    多个扩展名指向同一语言时各自一条参数，互不影响。
    """
    if not lang_map:
        return []
    args: List[str] = []
    # 按语言聚合便于日志可读
    grouped: Dict[str, List[str]] = {}
    for raw_ext, lang in lang_map.items():
        ext = raw_ext.strip()
        lang = (lang or "").strip()
        if not ext or not lang:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        grouped.setdefault(lang, []).append(ext)

    for lang, exts in grouped.items():
        for ext in exts:
            args.append(f"--map-{lang}=+{ext}")
        logger.info("🌐 lang_map: %s ⇐ %s", lang, ",".join(sorted(exts)))
    return args

def run_ctags(
    source_dir: str,
    lang_map: Optional[Dict[str, str]] = None,
) -> Iterable[dict]:
    """流式调用 ctags 并逐行 yield JSON 对象，避免大型仓库 stdout 撑爆内存。

    Args:
        source_dir: 待扫描目录。
        lang_map: 扩展名 → ctags 语言名（如 {".ets": "TypeScript"}），
                  用于让 ctags 把 ArkTS 等小众扩展名按 TS 解析。
                  若 value 命中内建语言（如 "Dart"），会自动注入随包分发的
                  规则文件，无需用户维护 ~/.ctags.d。
    """
    logger.info("⏳ [1/3] 调用 Universal Ctags 扫描: %s", source_dir)
    cmd: List[str] = ["ctags", "-R", "--output-format=json", "--fields=+nKsS"]
    # `--options` 必须在 `--map-<LANG>` 之前，因为后者引用的语言名要先经
    # `--langdef=<LANG>` 注册过才认得。
    cmd.extend(_resolve_builtin_options(lang_map))
    cmd.extend(_build_langmap_args(lang_map))
    cmd.append(source_dir)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except FileNotFoundError:
        logger.error("❌ 未找到 ctags 可执行文件，请先 'brew install universal-ctags'")
        return

    assert proc.stdout is not None
    count = 0
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
            count += 1
        except json.JSONDecodeError:
            logger.debug("跳过无法解析的 ctags 行: %.120s", line)

    err = proc.stderr.read() if proc.stderr else ""
    ret = proc.wait()
    if ret != 0:
        logger.error("❌ Ctags 退出码 %d: %s", ret, err.strip())
    logger.debug("ctags 共产出 %d 条符号", count)
