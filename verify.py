"""快速本地验证（不依赖 pytest / requests / tqdm）。"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
# 防止根目录脚本（如 run.py）等同名冲突，强制走 src 优先
sys.path = [p for p in sys.path if os.path.abspath(p) != ROOT]

from code2obsidian.models import FileNode  # noqa: E402
from code2obsidian.renderer import (  # noqa: E402
    render_markdown,
    safe_wiki_name,
    yaml_quote,
)
from code2obsidian.symbols import collect_symbols  # noqa: E402
from code2obsidian.config import load_config, find_config_path  # noqa: E402
from code2obsidian.cli import _build_parser, _merge_settings  # noqa: E402


def _verify_config_layer(tmp_root: str) -> None:
    """验证：配置文件 < CLI 显式参数；未知字段被忽略。"""
    import tempfile
    cfg_path = os.path.join(tmp_root, "code2obsidian.toml")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        fh.write("""
[code2obsidian]
threads = 16
model = "from-file"
bogus = "x"
""")
    cfg = load_config(cfg_path)
    assert cfg["threads"] == 16, cfg
    assert "bogus" not in cfg, cfg

    parser = _build_parser()
    # CLI 只显式给 --threads 4，model 应来自配置文件
    ns = parser.parse_args([
        "--config", cfg_path,
        "-o", "/tmp/out",
        "--threads", "4",
    ])
    merged = _merge_settings(ns)
    assert merged["threads"] == 4, merged          # CLI 胜出
    assert merged["model"] == "from-file", merged   # 来自配置文件
    assert merged["output"] == "/tmp/out", merged


def main() -> int:
    assert yaml_quote('a"b') == '"a\\"b"'
    assert yaml_quote("a\\b") == '"a\\\\b"'
    assert safe_wiki_name("a[b]c#d") == "a_b_c_d"

    node = FileNode(classes=["- `class Foo` (Line 1)"],
                    functions=["- `bar()` (Line 2)"])
    md = render_markdown("/abs/foo.py", "foo", ".py", node, "做 Foo 相关的事")
    assert 'summary: "做 Foo 相关的事"' in md
    assert "# 📄 foo.py" in md
    assert "无显式符号耦合" in md

    tags = [
        {"path": "/p/User.py", "name": "User", "kind": "class", "line": 1},
        {"path": "/p/UserService.py", "name": "UserService",
         "kind": "class", "line": 1, "inherits": "BaseService"},
        {"path": "/p/UserService.py", "name": "save", "kind": "method",
         "line": 5, "signature": "(self, u: User)"},
    ]
    vault, sym_map = collect_symbols(iter(tags))
    assert "User" in vault["/p/UserService.py"].requires
    assert "User" not in vault["/p/User.py"].requires

    tags2 = [
        {"path": "/a/Logger.py", "name": "Logger", "kind": "class", "line": 1},
        {"path": "/b/Logger.py", "name": "Logger", "kind": "class", "line": 1},
    ]
    _, sym_map2 = collect_symbols(iter(tags2))
    assert sym_map2["Logger"] == {"Logger"}

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        _verify_config_layer(d)

    print("ALL_CORE_TESTS_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
