"""并发处理流水线：LLM 摘要 + 落盘 + tqdm 进度条。"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, List, Tuple

from .logging_utils import logger
from .models import TaskCtx
from .ollama_client import get_ai_summary
from .renderer import render_markdown, safe_wiki_name


def process_single_file(ctx: TaskCtx, session: Any) -> Tuple[str, str]:
    """单文件处理：摘要 → 渲染 → 原子写。返回 (filename, status)。"""
    safe_stem = safe_wiki_name(ctx.pure_filename)
    md_path = os.path.join(ctx.output_dir, f"{safe_stem}.md")

    if (not ctx.force) and os.path.exists(md_path):
        return ctx.pure_filename, "skipped"

    if ctx.no_ai:
        ai_summary = "（已跳过 AI 摘要）"
    else:
        ai_summary = get_ai_summary(
            session,
            ctx.api_url,
            ctx.model_name,
            ctx.pure_filename + ctx.ext,
            ctx.node,
            ctx.timeout,
            ctx.retries,
        )

    md = render_markdown(ctx.raw_path, ctx.pure_filename, ctx.ext, ctx.node, ai_summary)
    tmp = md_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(md)
    os.replace(tmp, md_path)
    return ctx.pure_filename, ai_summary


def run_pipeline(tasks: List[TaskCtx], threads: int) -> Tuple[int, int, int]:
    """
    并发执行所有任务，带 tqdm 进度条；
    返回 (ok, skipped, failed) 计数。
    """
    if not tasks:
        return 0, 0, 0

    # 仅当真的需要 LLM 时才导入 requests，--no-ai 模式下完全零依赖可跑
    all_no_ai = all(t.no_ai for t in tasks)
    session: Any = None
    if not all_no_ai:
        import requests  # type: ignore
        session = requests.Session()

    try:
        from tqdm import tqdm  # type: ignore
        _has_tqdm = True
    except ImportError:  # pragma: no cover
        _has_tqdm = False

    ok = skipped = failed = 0

    with ThreadPoolExecutor(max_workers=threads) as ex:
        futures = {ex.submit(process_single_file, t, session): t for t in tasks}

        if _has_tqdm:
            bar = tqdm(
                as_completed(futures),
                total=len(futures),
                desc="📝 生成中",
                unit="file",
                ncols=100,
                dynamic_ncols=True,
            )
        else:
            logger.warning("⚠️ 未检测到 tqdm，进度条已降级为日志输出")
            bar = _FallbackBar(as_completed(futures), total=len(futures))
        for fut in bar:
            t = futures[fut]
            try:
                _, status = fut.result()
                if status == "skipped":
                    skipped += 1
                else:
                    ok += 1
                    bar.set_postfix_str(f"✅ {t.pure_filename}{t.ext}", refresh=False)
            except Exception as exc:
                failed += 1
                logger.warning("❌ 处理失败 %s: %s", t.raw_path, exc)
            bar.set_postfix(ok=ok, skip=skipped, fail=failed)
        bar.close()

    return ok, skipped, failed


class _FallbackBar:
    """tqdm 缺失时的极简降级实现，提供同样的接口。"""

    def __init__(self, iterable, total: int) -> None:
        self._it = iterable
        self._total = total
        self._done = 0

    def __iter__(self):
        for item in self._it:
            self._done += 1
            if self._done % 10 == 0 or self._done == self._total:
                logger.info("📝 进度 %d/%d", self._done, self._total)
            yield item

    def set_postfix_str(self, *_args, **_kwargs) -> None:
        return None

    def set_postfix(self, **_kwargs) -> None:
        return None

    def close(self) -> None:
        return None
