"""Universal Ctags 流式扫描封装。"""

from __future__ import annotations

import json
import subprocess
from typing import Dict, Iterable, List, Optional

from .logging_utils import logger


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
    """
    logger.info("⏳ [1/3] 调用 Universal Ctags 扫描: %s", source_dir)
    cmd: List[str] = ["ctags", "-R", "--output-format=json", "--fields=+nKsS"]
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
