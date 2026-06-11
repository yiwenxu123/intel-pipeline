[根目录](../CLAUDE.md) > **engine**

# engine — 领域无关情报引擎核心

## 模块职责

`engine/` 是整个项目的可复用内核：采集、LLM 筛选、存储、日报/API 输出、自动进化。所有业务语义通过 `domains/<name>/` 注入，引擎本身不硬编码领域知识。

## 入口与启动

| 入口 | 说明 |
|---|---|
| `engine/cli.py` | Click CLI，`intel` 命令（`pyproject.toml` 注册） |
| `engine/pipeline.py` | `run_full_pipeline()` — CLI `pipe` 与 `scripts/scheduler.py` 共用 |
| `python -m engine.cli -d <domain> <cmd>` | 开发时直接调用 |

CLI 命令：`fetch` → `filter` → `report` → `api` → `pipe`；`evolve` 子命令组用于进化分析。

## 子模块索引

| 子模块 | 职责 | 文档 |
|---|---|---|
| `fetcher/` | 多 kind 信源采集、关键词过滤、日期验证、去重入库 | [fetcher/CLAUDE.md](./fetcher/CLAUDE.md) |
| `filter/` | LLM 批量评分（OpenAI 兼容 API） | [filter/CLAUDE.md](./filter/CLAUDE.md) |
| `output/` | FastAPI REST、RSS、日报、飞书推送 | [output/CLAUDE.md](./output/CLAUDE.md) |
| `evolution/` | 信源质量、评分校准、关键词扩展、生命周期 | [evolution/CLAUDE.md](./evolution/CLAUDE.md) |

## 核心单文件模块

| 文件 | 职责 |
|---|---|
| `store.py` | SQLite：`raw_items`（含 `full_text` 列）、`scored_items`、`source_metrics`；URL MD5 去重 |
| `domain.py` | 从 `domains/<name>/` 加载 YAML/MD 配置为 `DomainConfig` |
| `models.py` | Pydantic 模型：`SourceDef`、`RawItem`、`ScoredItem`、`DailyReport` 等 |
| `config.py` | `Settings`（`INTEL_` 前缀环境变量），默认 `data/intel-{domain}.db` |

## 数据流

```
DomainConfig (domains/)
    ↓
fetch_all() → raw_items (SQLite, 全量入库)
    ↓
score_items() → scored_items (SQLite, 按 score_window_days 窗口)
    ↓
full_text_fetcher (pipe: score≥6 条目正文提取 → raw_items.full_text)
    ↓
generate_report() / FastAPI / RSS / notifier
    ↓
run_lifecycle_check() + keyword_staging + scoring_injector (pipe 后处理)
```

## 关键依赖与配置

- **运行时**：Python 3.11+，见 `pyproject.toml`（httpx、feedparser、openai、fastapi、click 等）
- **环境变量**：`.env` → `INTEL_LLM_*`、`INTEL_DOMAIN`、`INTEL_DB_PATH`、`INTEL_NOTIFY_WEBHOOK`
- **数据库**：每领域独立 SQLite 文件 `data/intel-{domain}.db`

## 测试与质量

- `tests/test_store.py` — 存储层 CRUD、去重、查询
- `tests/test_domain.py` — 领域配置加载
- `tests/test_filter.py` — JSON 解析（`_parse_json_array`）
- `tests/test_api.py` — FastAPI 端点（TestClient + 临时 DB）
- `tests/test_fetcher.py` — RSS/web 采集、关键词过滤、日期验证、全文提取（mock HTTP）
- `tests/test_evolution.py` — evolution 六子模块单元测试
- 质量工具：`ruff`（dev 依赖），无 CI 配置扫描到

## 常见问题 (FAQ)

**Q: CLI 的 `filter` 与 `pipe` 筛选逻辑有何不同？**  
A: `pipe` 通过 `pipeline.py` 调用，有 `max_items=50` 限制且日期容错更完善；独立 `filter` 命令处理窗口内全部未评分条目。

**Q: 预筛（pre_filter）还在用吗？**  
A: `filter/pipeline.py` 当前为单轮评分；`pre_filter.md` 仍被 `DomainConfig` 加载但主路径未调用 `pre_filter()`。

## 相关文件清单

```
engine/
├── cli.py, pipeline.py, store.py, domain.py, models.py, config.py
├── fetcher/   runner.py, rss_fetcher.py, web_fetcher.py, full_text_fetcher.py, ...
├── filter/    pipeline.py, llm_client.py
├── output/    api.py, report.py, notifier.py, templates/dashboard.html
└── evolution/ source_analyzer.py, scoring_calibrator.py, ...
```

## 常见修改场景

| 场景 | 修改位置 |
|---|---|
| 新增 CLI 命令 | `cli.py` |
| 调整 pipe 阶段顺序/逻辑 | `pipeline.py` |
| 扩展数据模型 | `models.py` + `store.py` 迁移 |
| 新增环境变量 | `config.py` + `.env.example` |
| 领域配置加载规则 | `domain.py` |

## 变更记录 (Changelog)

- **2026-06-11**：补充全文提取管道阶段、fetcher/evolution 测试、常见修改场景表
- **2026-06-10**：init-architect 初始化模块文档
