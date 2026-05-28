"""命令行入口。"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional, Set

from . import __version__
from .config import SAMPLE_TOML, find_config_path, load_config
from .ctags import run_ctags
from .logging_utils import logger, setup_logging
from .models import TaskCtx
from .pipeline import run_pipeline
from .symbols import collect_symbols

# 所有可配置项的「默认值表」——也是配置合并的最后一层兏底
DEFAULTS: Dict[str, Any] = {
    "source": "./src",
    "output": None,           # 必填，无默认
    "model": "qwen3:8b",
    "url": "http://localhost:11434/api/generate",
    "threads": 8,
    "timeout": 30,
    "retries": 2,
    "include_ext": "",
    "no_ai": False,
    "force": False,
    "verbose": False,
    "lang_map": {},  # {".ets": "TypeScript", ...}
    # 增量分析：未指定 diff_from 时走全量流程
    "diff_from": None,
    "diff_to": "HEAD",
    "diff_report": None,
}

def _build_parser() -> argparse.ArgumentParser:
    """
    构建 argparse。**关键**：所有业务参数都用 SUPPRESS 当默认值，
    这样未在命令行出现的字段不会进入 namespace，便于与配置文件合并。
    """
    parser = argparse.ArgumentParser(
        prog="code2obsidian",
        description="🚀 Code2Obsidian: Ctags 物理符号网 + 本地 Ollama 语义注入的一体化图谱工具",
    )
    parser.add_argument("-s", "--source", default=argparse.SUPPRESS,
                        help="源码目录路径（默认 ./src）")
    parser.add_argument("-o", "--output", default=argparse.SUPPRESS,
                        help="Obsidian 沙盒目标目录的绝对路径（必填，可写在配置文件里）")
    parser.add_argument("--model", default=argparse.SUPPRESS,
                        help="本地 Ollama 模型名称（默认 qwen3:8b）")
    parser.add_argument("--url", default=argparse.SUPPRESS,
                        help="Ollama /api/generate 端点")
    parser.add_argument("--threads", type=int, default=argparse.SUPPRESS,
                        help="并发线程数（默认 8）")
    parser.add_argument("--timeout", type=int, default=argparse.SUPPRESS,
                        help="单次 LLM 请求超时秒数（默认 30）")
    parser.add_argument("--retries", type=int, default=argparse.SUPPRESS,
                        help="LLM 请求失败重试次数（默认 2）")
    parser.add_argument("--include-ext", default=argparse.SUPPRESS,
                        help="只处理指定扩展名（逗号分隔，如 .py,.ts,.go）；空=全部")
    parser.add_argument("--no-ai", action="store_true", default=argparse.SUPPRESS,
                        help="跳过 LLM 摘要，仅生成确定性骨架")
    parser.add_argument("--force", action="store_true", default=argparse.SUPPRESS,
                        help="强制覆盖已有 md（默认开启断点续跑）")
    parser.add_argument("-v", "--verbose", action="store_true",
                        default=argparse.SUPPRESS, help="输出调试日志")

    parser.add_argument("--lang-map", default=argparse.SUPPRESS,
                        help="将扩展名视为某种语言让 ctags 解析，逗号分隔。"
                             "如：--lang-map .ets=TypeScript,.mts=TypeScript")

    # ---- 增量分析（可选）----
    parser.add_argument("--diff-from", default=argparse.SUPPRESS,
                        help="增量分析起点 commit / 分支 / tag；"
                             "提供后只重建变更文件的 md，并生成变更报告")
    parser.add_argument("--diff-to", default=argparse.SUPPRESS,
                        help="增量分析终点（默认 HEAD）")
    parser.add_argument("--diff-report", default=argparse.SUPPRESS,
                        help="变更报告输出路径（默认放在 output 目录下，"
                             "命名为 _CHANGES_<from>_<to>.md）")

    # 元控制参数（不属于业务字段，正常给默认值）
    parser.add_argument("-c", "--config", default=None,
                        help="显式指定配置文件路径（默认查找 ./code2obsidian.toml）")
    parser.add_argument("--init-config", metavar="PATH", default=None,
                        help="生成一份示例配置文件到指定路径，然后退出")
    parser.add_argument("-V", "--version", action="version",
                        version=f"%(prog)s {__version__}")
    return parser


def _parse_include_exts(raw: str) -> Optional[Set[str]]:
    raw = (raw or "").strip()
    if not raw:
        return None
    return {
        (e if e.startswith(".") else "." + e).lower()
        for e in raw.split(",") if e.strip()
    }


def _parse_lang_map_cli(raw: Any) -> Dict[str, str]:
    """解析 CLI --lang-map 参数。输入如 '.ets=TypeScript,.mts=TypeScript'。"""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    out: Dict[str, str] = {}
    for pair in str(raw).split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        ext, _, lang = pair.partition("=")
        ext = ext.strip()
        lang = lang.strip()
        if not ext or not lang:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        out[ext.lower()] = lang
    return out


def _normalize_lang_map(raw: Any) -> Dict[str, str]:
    """统一备选源（CLI 字符串 / TOML dict）为规范化后的 dict。"""
    if isinstance(raw, dict):
        out: Dict[str, str] = {}
        for k, v in raw.items():
            ext = str(k).strip().lower()
            lang = str(v).strip()
            if not ext or not lang:
                continue
            if not ext.startswith("."):
                ext = "." + ext
            out[ext] = lang
        return out
    return _parse_lang_map_cli(raw)


def _merge_settings(cli_ns: argparse.Namespace) -> Dict[str, Any]:
    """三层合并：DEFAULTS < 配置文件 < CLI 显式参数。返回最终扁平 dict。"""
    cli_dict: Dict[str, Any] = {
        k.replace("-", "_"): v for k, v in vars(cli_ns).items()
    }

    # 配置文件查找需要 source（CLI 优先）
    src_for_lookup = cli_dict.get("source") or DEFAULTS["source"]
    cfg_path = find_config_path(cli_dict.pop("config", None), src_for_lookup)

    file_settings: Dict[str, Any] = load_config(cfg_path) if cfg_path else {}

    merged: Dict[str, Any] = dict(DEFAULTS)
    merged.update(file_settings)
    # CLI 里凡是出现的字段（哪怕是 False/空串）都视作显式覆盖
    for k, v in cli_dict.items():
        if k in DEFAULTS:
            merged[k] = v
    return merged


def _write_sample_config(path: str) -> int:
    if os.path.exists(path):
        logger.error("❌ 目标已存在，拒绝覆盖: %s", path)
        return 1
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(SAMPLE_TOML)
    logger.info("✅ 已生成示例配置: %s", path)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    cli_ns = parser.parse_args(argv)

    # --init-config 是元命令，最先处理
    init_target = getattr(cli_ns, "init_config", None)
    if init_target:
        # 这里临时把日志开起来便于看到结果
        setup_logging(getattr(cli_ns, "verbose", False))
        return _write_sample_config(init_target)

    cfg = _merge_settings(cli_ns)
    setup_logging(cfg["verbose"])

    if not cfg.get("output"):
        parser.error("缺少 --output（也未在配置文件里提供 output 字段）")

    output = cfg["output"]
    if not os.path.isabs(output):
        logger.warning("⚠️ output 建议使用绝对路径: %s", output)
    os.makedirs(output, exist_ok=True)

    include_exts = _parse_include_exts(cfg["include_ext"])
    lang_map = _normalize_lang_map(cfg.get("lang_map"))
    # 如果用户限定了扩展名，自动把 lang_map 中的 key 也加入白名单，
    # 避免“--include-ext .ts 却过滤掉被视为 TS 的 .ets”这种逆直觉陷阱。
    if include_exts and lang_map:
        added = set(lang_map.keys()) - include_exts
        if added:
            include_exts = include_exts | set(lang_map.keys())
            logger.info(
                "🔗 lang_map 自动打通 include_ext：新增 %s",
                ",".join(sorted(added)),
            )
    if include_exts:
        logger.info("📎 仅处理扩展名: %s", ",".join(sorted(include_exts)))

    tags_iter = run_ctags(cfg["source"], lang_map=lang_map)
    file_vault, global_symbol_map = collect_symbols(tags_iter, include_exts)

    if not file_vault:
        logger.error("❌ 未扫描到任何有效符号，请检查 source 路径与 ctags 是否可用")
        return 1

    logger.info(
        "🧬 [2/3] 全局物理符号网建立完成：%d 个核心类型 / %d 个文件",
        len(global_symbol_map), len(file_vault),
    )

    # 增量模式分流：指定了 diff_from 就只处理变更文件 + 反向依赖
    if cfg.get("diff_from"):
        return _run_incremental(cfg, file_vault, output)

    tasks: List[TaskCtx] = []
    for raw_path, node in file_vault.items():
        pure_filename = os.path.splitext(os.path.basename(raw_path))[0]
        ext = os.path.splitext(raw_path)[1]
        tasks.append(TaskCtx(
            raw_path=raw_path,
            node=node,
            pure_filename=pure_filename,
            ext=ext,
            output_dir=output,
            api_url=cfg["url"],
            model_name=cfg["model"],
            timeout=cfg["timeout"],
            retries=cfg["retries"],
            no_ai=cfg["no_ai"],
            force=cfg["force"],
        ))

    logger.info(
        "🚀 [3/3] 启动并发摘要（线程: %d, 模型: %s, AI: %s）",
        cfg["threads"], cfg["model"], "off" if cfg["no_ai"] else "on",
    )

    ok, skipped, failed = run_pipeline(tasks, cfg["threads"])
    logger.info(
        "🎉 完成！成功 %d / 跳过 %d / 失败 %d → %s",
        ok, skipped, failed, output,
    )
    return 0 if failed == 0 else 2


def _run_incremental(
    cfg: Dict[str, Any],
    file_vault: Dict[str, Any],
    output: str,
) -> int:
    """增量模式：只重建 diff 范围内 + 反向依赖文件的 md，并生成变更报告。"""
    from .incremental import (
        diff_files,
        handle_deletions,
        render_changes_report,
        reverse_deps_of,
    )

    commit_a = cfg["diff_from"]
    commit_b = cfg.get("diff_to") or "HEAD"
    include_exts = _parse_include_exts(cfg["include_ext"])

    try:
        git_root, changes = diff_files(
            cfg["source"], commit_a, commit_b, include_exts,
        )
    except RuntimeError as e:
        logger.error("❌ 增量分析失败: %s", e)
        return 1

    if not changes:
        logger.info("✨ 在 %s..%s 之间没有发现匹配的源码变更，无需更新", commit_a, commit_b)
        return 0

    by_status: Dict[str, int] = {"A": 0, "M": 0, "D": 0, "R": 0}
    for c in changes:
        by_status[c.status] = by_status.get(c.status, 0) + 1
    logger.info(
        "🔄 [增量] git diff %s..%s → 修改 %d / 新增 %d / 重命名 %d / 删除 %d（git_root: %s）",
        commit_a, commit_b,
        by_status.get("M", 0), by_status.get("A", 0),
        by_status.get("R", 0), by_status.get("D", 0),
        git_root,
    )

    # 1) 处理删除：从 vault 物理删除对应 md
    deletions = [c for c in changes if c.is_delete]
    deleted_basenames = handle_deletions(deletions, output)

    # 2) 找反向依赖文件（旧 vault 里 requires 包含变更/删除文件 basename 的）
    changed_basenames = {c.basename for c in changes}
    affected_paths = reverse_deps_of(output, changed_basenames)
    # 反向依赖文件如果它本身就在 changes 里，避免重复
    in_changes = {c.path for c in changes}
    affected_paths -= in_changes
    if affected_paths:
        logger.info("🔁 反向依赖刷新：%d 个文件", len(affected_paths))

    # 3) 构建任务：变更文件（非删除） + 反向依赖文件
    change_by_path = {c.path: c for c in changes if not c.is_delete}
    target_paths: List[str] = list(change_by_path.keys()) + list(affected_paths)

    tasks: List[TaskCtx] = []
    missing: List[str] = []
    for raw_path in target_paths:
        node = file_vault.get(raw_path)
        if node is None:
            # 该文件在终点 commit 不存在或被 ctags 跳过
            missing.append(raw_path)
            continue
        pure_filename = os.path.splitext(os.path.basename(raw_path))[0]
        ext = os.path.splitext(raw_path)[1]
        tasks.append(TaskCtx(
            raw_path=raw_path,
            node=node,
            pure_filename=pure_filename,
            ext=ext,
            output_dir=output,
            api_url=cfg["url"],
            model_name=cfg["model"],
            timeout=cfg["timeout"],
            retries=cfg["retries"],
            no_ai=cfg["no_ai"],
            force=True,                 # 增量模式下本来就要覆盖
            reuse_old_summary=True,     # 优先复用旧 LLM 摘要
            change=change_by_path.get(raw_path),  # 反向依赖文件无 change
            commit_a=commit_a,
            commit_b=commit_b,
        ))

    if missing:
        logger.warning(
            "⚠️ %d 个变更/反向依赖文件未在 ctags 输出中出现（可能是非源码或 include_ext 过滤）：%s",
            len(missing), ", ".join(os.path.basename(p) for p in missing[:5]),
        )

    if tasks:
        logger.info(
            "🚀 [增量] 启动重建（线程: %d, 模型: %s, AI: %s, 复用旧摘要: 是）",
            cfg["threads"], cfg["model"], "off" if cfg["no_ai"] else "on",
        )
        ok, skipped, failed = run_pipeline(tasks, cfg["threads"])
    else:
        ok = skipped = failed = 0

    # 4) 生成变更报告
    report_path = cfg.get("diff_report")
    if not report_path:
        # 默认放在 output 下
        safe_a = commit_a.replace("/", "_")[:12]
        safe_b = commit_b.replace("/", "_")[:12]
        report_path = os.path.join(output, f"_CHANGES_{safe_a}_{safe_b}.md")
    report_md = render_changes_report(
        commit_a, commit_b, changes, file_vault, output, affected_paths,
    )
    os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(report_md)
    logger.info("📝 变更报告 → %s", report_path)

    logger.info(
        "🎉 [增量] 完成！更新 %d / 跳过 %d / 失败 %d / 删除 %d / 反向依赖 %d → %s",
        ok, skipped, failed, len(deleted_basenames), len(affected_paths), output,
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
