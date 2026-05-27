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

# 所有可配置项的「默认值表」——也是配置合并的最后一层兜底
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
    if include_exts:
        logger.info("📎 仅处理扩展名: %s", ",".join(sorted(include_exts)))

    tags_iter = run_ctags(cfg["source"])
    file_vault, global_symbol_map = collect_symbols(tags_iter, include_exts)

    if not file_vault:
        logger.error("❌ 未扫描到任何有效符号，请检查 source 路径与 ctags 是否可用")
        return 1

    logger.info(
        "🧬 [2/3] 全局物理符号网建立完成：%d 个核心类型 / %d 个文件",
        len(global_symbol_map), len(file_vault),
    )

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


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
