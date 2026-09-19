# Skill Office Agent

基于 **SKILL.md** 的技能化办公 Agent：用 Markdown 描述文件定义技能，Agent 自动路由意图、串行调用多技能、通过 Function Calling 执行工具，并内置超时重试与失败降级。

全部代码、技能、数据与运行入口均位于 **D 盘**：`D:\skill-office-agent`。

## 核心能力

| 模块 | 说明 |
|------|------|
| 技能封装 | 5 个办公技能，各含 `SKILL.md`（YAML frontmatter + 指令）+ `scripts/run.py` |
| 路由机制 | 关键词/描述打分 + 多技能流水线规则 + 可选 LLM Function Calling 路由 |
| 工具调用 | 11 个 Function Calling 工具（本地文件、表格统计、网络搜索、Python 脚本等） |
| 容错处理 | 超时、指数退避重试、熔断器、网络失败降级本地知识库、模板占位降级 |

## 技能清单（skills/）

1. **file-search** — 本地文件检索（文件名/扩展名/内容）
2. **table-stats** — CSV/Excel 描述统计与分组汇总
3. **report-gen** — 结构化 Markdown 报告生成
4. **web-search** — 网络信息查询（失败自动降级 `knowledge/office_kb.json`）
5. **email-draft** — 办公邮件/通知草稿

每个技能目录结构遵循渐进披露：

```
skills/table-stats/
├── SKILL.md          # frontmatter(触发时机/关键词/工具/超时/降级) + 执行指令
└── scripts/run.py    # 可被子进程调用的入口，stdin JSON → stdout JSON
```

## 目录结构

```
D:\skill-office-agent\
├── run_cli.py            # 命令行入口
├── run_desktop.py        # 桌面 GUI (tkinter)
├── config.json           # 路由/容错/LLM 配置
├── agent/                # Agent 核心（注册表/路由/执行器/编排）
├── skills/               # SKILL.md 技能包
├── tools/                # Function Calling 工具实现
├── knowledge/            # 本地知识库（搜索降级兜底）
├── templates/            # 报告/邮件模板
├── data/samples/         # 示例表格
├── data/workspace/       # 报告与邮件输出
├── logs/                 # 会话 JSON 日志
└── tests/test_agent.py   # 端到端测试
```

## 快速开始

```powershell
# 使用 MiMo 内置 Python（或任意 Python 3.10+）
cd D:\skill-office-agent

# 查看技能与工具
& $env:MIMO_PYTHON run_cli.py skills
& $env:MIMO_PYTHON run_cli.py tools

# 仅看路由
& $env:MIMO_PYTHON run_cli.py route "找到销售表并统计各区域销售额，生成报告"

# 端到端执行（多技能串行）
& $env:MIMO_PYTHON run_cli.py run "找到销售表并统计各区域销售额，生成报告并起草同步邮件" --args-file "D:\skill-office-agent\data\workspace\demo_args.json"

# 网络查询（失败自动降级本地知识库）
& $env:MIMO_PYTHON run_cli.py run "搜索一下远程办公协作要点"

# 直接 Function Calling（PowerShell 注意引号，或使用 --args-file）
& $env:MIMO_PYTHON run_cli.py call-tool search_files --args '{\"query\":\"sales\",\"root\":\"D:/skill-office-agent/data\"}'

# 一键演示脚本
powershell -File D:\skill-office-agent\examples\run_demo.ps1

# 交互模式
& $env:MIMO_PYTHON run_cli.py run

# 桌面 GUI
& $env:MIMO_PYTHON run_desktop.py
```

## 路由机制

执行优先级：

1. **显式技能名** — 用户消息中包含 `table-stats` 等
2. **流水线规则** — 正则匹配多技能组合，如「找…统计…报告」→ `file-search → table-stats → report-gen`
3. **LLM Function Calling** — 若在 `config.json` / 环境变量配置了 OpenAI 兼容端点，则调用 `select_skills` 工具选链
4. **混合打分** — 关键词命中 + 描述 token 重叠 + 互补技能对串联
5. **兜底** — 低置信时取最高分技能

配置 LLM 路由（可选）：

```json
"llm": {
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-...",
  "model": "gpt-4o-mini"
}
```

或环境变量：`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`。

未配置 LLM 时完全离线可用（规则路由 + 本地执行 + 本地知识库）。

### Agent 执行模式（AI 接入）

| mode | 行为 |
|------|------|
| `rule` | 纯规则技能链 + 本地工具/模板 |
| `llm_agent` | 模型 Function Calling 自主调工具；LLM 未配置或失败时**自动回落** rule |
| `hybrid`（默认） | 规则串技能；配置了 LLM 时，`report-gen` / `email-draft` 用模型生成终稿，失败仍用模板 |

配置示例（`config.json`）：

```json
"llm": { "base_url": "https://api.openai.com/v1", "api_key": "sk-...", "model": "gpt-4o-mini", "polish": true },
"agent": { "mode": "hybrid", "llm_max_rounds": 4 }
```

命令行覆盖模式：

```powershell
& $env:MIMO_PYTHON run_cli.py run "找到销售表并统计销售额，生成报告" --mode rule
& $env:MIMO_PYTHON run_cli.py run "查找并汇总数据，写报告" --mode llm_agent
& $env:MIMO_PYTHON run_cli.py run "生成报告并起草邮件" --mode hybrid
```

环境变量也可覆盖：`SKILL_AGENT_MODE` / `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`。

## Function Calling 工具

`tools/__init__.py` 中的 `FUNCTION_CALLING_TOOLS` 提供 OpenAI 风格 schema，`dispatch_tool()` 本地执行：

- 文件系统：`list_files` / `search_files` / `read_file_meta`
- 表格：`read_table` / `describe_table` / `group_by_table`
- 信息：`search_web` / `search_knowledge_base`
- 输出：`write_file`
- 扩展：`run_python_script` / `run_inline_python`

有 LLM 配置时：`run(..., mode="llm_agent")` 会走 `LLMClient.run_function_calling_loop`（模型选工具 → 本地执行 → 回传）；`hybrid`/`rule` 下报告与邮件技能可选调用模型润色终稿（`tools/llm_text.py`，失败回落模板）。

## 容错策略

| 场景 | 行为 |
|------|------|
| 技能脚本超时 | 按 `SKILL.md` 的 `timeout` 杀子进程；按 `retries` + 指数退避重试 |
| 技能执行失败 | 读取 `fallback` 字段降级：`knowledge_base` / `template_only` |
| 网络搜索失败/空结果 | 自动切换 `knowledge/office_kb.json`，结果标记 `degraded=true` |
| 同一技能连续失败 | 熔断器打开（默认 60s），期间快速失败避免雪崩 |
| 上游结果串联 | 报告/邮件技能可消费前序技能的 JSON；路径可自动从 file-search 注入 table-stats |

## 扩展新技能

1. 新建 `skills/<kebab-name>/SKILL.md`，frontmatter 至少包含 `name` 与 `description`（写清 WHAT + WHEN + 用户口头触发词），并声明 `keywords` / `entry` / `timeout` / `retries` / `tools` / `fallback`。
2. 编写 `scripts/run.py`：从 stdin 读 JSON 参数，向 stdout 打印 JSON 结果，键包含 `skill/ok/...`。
3. 如需新工具，在 `tools/` 实现函数，并加入 `FUNCTION_CALLING_TOOLS` 与 `dispatch_tool`。
4. 若技能可组成流水线，在 `agent/router.py` 的 `PIPELINES` 增加一条模式。
5. 重启 Agent 或 CLI 执行 `skills` 命令确认已加载。

## 测试

```powershell
cd D:\skill-office-agent
& $env:MIMO_PYTHON -m unittest tests.test_agent -v
```

覆盖：技能加载、意图路由、工具调用、参数抽取、多技能串行、网络降级、报告/邮件落盘。

## 示例输出文件

- 报告：`D:\skill-office-agent\data\workspace\report_*.md`
- 邮件：`D:\skill-office-agent\data\workspace\email_*.txt`
- 会话日志：`D:\skill-office-agent\logs\session_*.json`
