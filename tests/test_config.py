"""config 模块单元测试（无外部依赖）。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from code2obsidian.config import (  # noqa: E402
    ALLOWED_KEYS,
    find_config_path,
    load_config,
)


def _write(tmp: Path, name: str, body: str) -> str:
    p = tmp / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_load_config_top_level_and_section_merge():
    with tempfile.TemporaryDirectory() as d:
        path = _write(Path(d), "code2obsidian.toml", """
threads = 1

[code2obsidian]
threads = 16
model = "qwen3:8b"

[tool.code2obsidian]
threads = 32
verbose = true
""")
        cfg = load_config(path)
    # tool.code2obsidian 优先级最高
    assert cfg["threads"] == 32
    assert cfg["model"] == "qwen3:8b"
    assert cfg["verbose"] is True


def test_load_config_unknown_keys_filtered():
    with tempfile.TemporaryDirectory() as d:
        path = _write(Path(d), "code2obsidian.toml", """
[code2obsidian]
threads = 4
nonsense_field = "x"
""")
        cfg = load_config(path)
    assert "nonsense_field" not in cfg
    assert cfg["threads"] == 4
    # 白名单稳定性兜底
    assert "threads" in ALLOWED_KEYS


def test_find_config_path_explicit_missing(tmp_path=None):
    # explicit 不存在 → None
    assert find_config_path("/no/such/file.toml", None) is None


def test_find_config_path_in_source_dir():
    with tempfile.TemporaryDirectory() as d:
        sub = Path(d) / "src"
        sub.mkdir()
        cfg = sub / "code2obsidian.toml"
        cfg.write_text("threads = 2\n", encoding="utf-8")
        # 切换到无配置的临时 cwd，避免命中 ./code2obsidian.toml
        prev = os.getcwd()
        os.chdir(d)
        try:
            found = find_config_path(None, str(sub))
        finally:
            os.chdir(prev)
        assert found == str(cfg)
