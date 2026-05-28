# 🚀 Code2Obsidian

> 基于 **Universal Ctags** 的 100% 确定性符号扫描，叠加 **本地 Ollama** 并发语义摘要，
> 一键把任意代码库织成 **Obsidian 知识图谱**。

```
ctags 流式扫描  →  跨文件符号网（精准单词边界匹配）
                     ↓
              本地 Ollama 并发摘要（重试 + 断点续跑）
                     ↓
        Markdown + YAML frontmatter + Wiki-link 双链
```

## ✨ 特性

- **100% 确定性骨架**：类/方法/字段/继承/签名 全量提取
- **精准依赖**：单词边界正则杜绝 `User → UserService` 误匹配
- **本地 LLM 摘要**：默认走 `qwen3:8b`，自带超时 + 重试 + `<think>` 噪声清洗
- **断点续跑**：默认跳过已生成的 md，`--force` 才覆盖
- **🔄 增量分析**：基于 `git diff` 的两 commit 区间增量重建，复用旧 LLM 摘要 + 反向依赖刷新 + 变更总览报告
- **进度条**：`tqdm` 实时显示成功 / 跳过 / 失败计数
- **流式 ctags**：超大仓库不会撑爆内存
- **原子写**：`.tmp` + `os.replace`，防止半截文件
- **工程化**：`src/` 布局 / `pyproject.toml` / 入口脚本 / 类型注解 / 模块化

## 📦 安装

### 1. 系统依赖

```bash
# macOS
brew install universal-ctags

# Ubuntu / Debian
sudo apt install universal-ctags
```

### 2. Python 依赖

```bash
pip install -r requirements.txt
```

或使用现代化方式安装为命令行工具：

```bash
pip install -e .
```

安装后即可在终端直接使用 `code2obsidian` 命令。

### 3. 启动本地 Ollama

```bash
ollama pull qwen3:8b
ollama serve
```

## 🛠 使用

### 三种调用方式（任选其一）

```bash
# 1. 已 pip install -e . 后
code2obsidian -s ./src -o /Users/you/Vault/CodeWiki

# 2. 模块方式
python -m code2obsidian -s ./src -o /Users/you/Vault/CodeWiki

# 3. 兼容老用法（无需安装）
python run.py -s ./src -o /Users/you/Vault/CodeWiki
```

### 常用选项

| 选项 | 说明 | 默认值 |
|---|---|---|
| `-s, --source` | 源码目录 | `./src` |
| `-o, --output` | Obsidian 目标目录（建议绝对路径） | **必填** |
| `--model` | Ollama 模型名 | `qwen3:8b` |
| `--url` | Ollama 端点 | `http://localhost:11434/api/generate` |
| `--threads` | 并发线程数 | `8` |
| `--timeout` | 单次 LLM 超时（秒） | `30` |
| `--retries` | LLM 失败重试次数 | `2` |
| `--include-ext` | 仅处理扩展名（逗号分隔，如 `.py,.ts`） | 全部 |
| `--lang-map` | 把扩展名视为某语言（如 `.ets=TypeScript`） | 空 |
| `--no-ai` | 跳过 LLM，仅生成确定性骨架 | 关 |
| `--force` | 覆盖已存在的 md | 关（断点续跑） |
| `--diff-from` | **增量模式起点** commit / 分支 / tag（提供后启用增量分析） | — |
| `--diff-to` | 增量模式终点 | `HEAD` |
| `--diff-report` | 变更报告输出路径 | `<output>/_CHANGES_<a>_<b>.md` |
| `-v, --verbose` | 调试日志 | 关 |
| `-V, --version` | 版本号 | — |

### 实战示例

```bash
# 仅前端 + 跳过 AI（CI 友好）
code2obsidian -s ./web/src -o ~/Vault/Web \
    --include-ext .ts,.tsx,.js --no-ai --force

# Go 项目 + 自定义模型 + 16 并发
code2obsidian -s ./services -o ~/Vault/Backend \
    --include-ext .go --model deepseek-coder:6.7b --threads 16
```

## 🔄 增量分析（Git Diff）

首次全量建好知识库之后，只要传入 `--diff-from`，就会进入**增量模式**：
仅重建变更文件 + 受影响的反向依赖文件，并额外产出一份「**变更总览报告**」，
非常适合**排 bug、Code Review、版本对比**等场景。

### 用法

```bash
# 1. 排 bug：看最近 5 个 commit 改动了什么
code2obsidian -s ./src -o ~/Vault/CodeWiki \
    --diff-from HEAD~5

# 2. 跨分支对比（feature 分支引入了什么）
code2obsidian -s ./src -o ~/Vault/CodeWiki \
    --diff-from main --diff-to feature/foo

# 3. 自定义报告输出路径
code2obsidian -s ./src -o ~/Vault/CodeWiki \
    --diff-from v1.0 --diff-to v1.1 \
    --diff-report /tmp/v1.0-to-v1.1.md
```

### 增量模式做了什么

| 行为 | 说明 |
|---|---|
| **变更识别** | `git diff -M` 抓取 A/M/D/R 四类动作，自动识别重命名 |
| **反向依赖刷新** | 扫描旧 vault，把 `requires` 命中变更文件的 md 也加入重建列表（依赖网不会陈旧） |
| **🔥 最近变更小节** | 每个变更文件 md 顶部插入「区间 / 行数 / 状态」徽章块 |
| **复用旧 summary** | 增量模式默认**不重跑昂贵的 LLM**——直接从旧 md 的 frontmatter 取 `summary`，缺失时才调 Ollama |
| **删除清理** | git 已删除的源码，对应 md 会被物理移除 |
| **变更报告** | 单独生成 `_CHANGES_<from>_<to>.md`，按 ✏️/🆕/🔀/🗑️ 分组列出每个文件的符号统计与依赖列表 |

### 输出示例

```
🔄 [增量] git diff abc1234..HEAD → 修改 6 / 新增 0 / 重命名 0 / 删除 0
🔁 反向依赖刷新：4 个文件
🚀 [增量] 启动重建（线程: 8, 模型: qwen3:8b, AI: on, 复用旧摘要: 是）
📝 变更报告 → ~/Vault/CodeWiki/_CHANGES_abc1234_HEAD.md
🎉 [增量] 完成！更新 10 / 跳过 0 / 失败 0 / 删除 0 / 反向依赖 4
```

> 💡 **零回归**：未传 `--diff-from` 时走的就是和以前完全一致的全量流程。
>
> ⚠️ **前提**：`source` 目录必须位于 git 仓库内，否则会直接报错并提示。

## 🗂 配置文件（可选）

每个项目都可以放一个 `code2obsidian.toml`，把常用参数固化下来：

```bash
# 一键生成示例
code2obsidian --init-config ./code2obsidian.toml
```

```toml
# code2obsidian.toml
[code2obsidian]
source = "./src"
output = "/Users/you/Vault/CodeWiki"
model = "qwen3:8b"
threads = 16
include_ext = ".py,.ts,.go"
no_ai = false
force = false
```

之后命令行可以省略所有参数：

```bash
code2obsidian                        # 自动加载 ./code2obsidian.toml
code2obsidian -c ~/cfg/c2o.toml      # 显式指定
code2obsidian --threads 32           # CLI 实参覆盖文件中的 threads
```

**优先级**：`命令行实参 > 配置文件 > 内置默认值`。

**查找顺序**：`--config 显式路径` → `./code2obsidian.toml` → `<source>/code2obsidian.toml`。

> Python 3.11+ 使用标准库 `tomllib` 解析；3.10 及以下若已安装 `tomli` 则使用之，
> 否则自动回退到内置 mini 解析器（覆盖本工具所需的标量/嵌套段语法，零额外依赖）。

## 🌐 语言映射（让 ctags 认识小众语言）

ctags 默认不识别一些扩展名（如 HarmonyOS **ArkTS `.ets`**），但它们的语法往往是某种主流语言的"近亲"。
通过 `lang_map` 可以告诉 ctags："**把这个扩展名按那种语言来解析**"——一行配置即可让 ArkTS / Vue SFC / 自定义模板等纳入符号网。

**配置文件写法**（推荐）：

```toml
[code2obsidian.lang_map]
".ets" = "TypeScript"     # ArkTS 视为 TS
".mts" = "TypeScript"
".cts" = "TypeScript"
```

**命令行写法**（等价）：

```bash
code2obsidian -s ./entry/src -o ~/Vault/HarmonyOS \
    --include-ext .ts \
    --lang-map ".ets=TypeScript,.mts=TypeScript"
```

> 💡 **智能联动**：当你同时使用 `--include-ext .ts` 和 `lang_map`，工具会自动把 `.ets` 等被映射的扩展名一起放行，无需手动加。
>
> 📋 用 `ctags --list-languages` 可以查看你本地 ctags 支持的所有语言名。


## 🧱 项目结构

```
code2obsidian/
├── README.md
├── requirements.txt
├── pyproject.toml
├── run.py                      # 兼容入口（无需安装即可 python run.py 直接运行）
└── src/
    └── code2obsidian/
        ├── __init__.py
        ├── __main__.py         # python -m code2obsidian
        ├── cli.py              # 命令行参数 + 主流程
        ├── ctags.py            # ctags 流式扫描
        ├── symbols.py          # 符号网构建（精准依赖）
        ├── ollama_client.py    # LLM 摘要 + 重试
        ├── renderer.py         # YAML / wiki-link / markdown
        ├── pipeline.py         # 并发执行 + tqdm 进度条
        ├── incremental.py      # 🔄 git diff 增量分析 + 变更报告
        ├── models.py           # FileNode / TaskCtx
        └── logging_utils.py
```

## 🧪 开发

```bash
pip install -e ".[dev]"
pytest -q
ruff check src
```