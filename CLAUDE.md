# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

**Intel Pipeline** 是一个多领域可插拔情报采集、筛选、展示引擎。支持领域通过 `domains/` 目录配置，引擎代码 (`engine/`) 完全领域无关。

当前支持领域：`elderly-care`（银发产业）、`china-africa`（中非经贸）

## 核心架构

### 流水线

```
sources.yaml → [Fetcher] → SQLite(raw_items) → [LLM Filter] → SQLite(scored_items) → API/日报
```

四个阶段：`fetch` → `filter` → `report` → `api`，一键执行 `pipe`。

### 模块分层

- **engine/fetcher/** — 采集层。每种 `kind`（rss/web/ageclub/searxng）有独立 fetcher，统一返回 `RawItem`。`runner.py` 负责并发调度、关键词过滤、日期验证补全
- **engine/filter/** — LLM 筛选层。两轮流水线：`pre_filter()`（低成本模型去噪，批量 Y/N 决策）→ `score_items()`（强模型批量评分，输出 JSON 数组含 score/category/summary 等）
- **engine/output/** — 输出层。`api.py` 提供 FastAPI REST API + RSS Feed，`report.py` 生成 Markdown/JSON 日报
- **engine/evolution/** — 自动进化模块。`source_analyzer.py`（信源质量统计）、`scoring_calibrator.py`（评分分析）、`keyword_expander.py`（关键词扩展）
- **engine/store.py** — SQLite 存储层，URL MD5 去重
- **engine/domain.py** — 领域加载器，从 `domains/<name>/` 读取全部配置
- **engine/models.py** — Pydantic 数据模型：`SourceDef`、`RawItem`、`ScoredItem`、`DailyReport`

### 关键设计决策

- **采集全量入库**，不做时间过滤；LLM 只筛最近 N 天（`score_window_days`）未评分条目以控成本
- **分类独立时间窗口**：每个 category 在 `categories.yaml` 中有 `freshness_days`，API 按此过滤（政策30天、风险3天）
- **日期验证**：无日期的条目通过 `date_verifier.py` 尝试从原文提取，仍然无日期则不入库
- **LLM 调用**通过 OpenAI 兼容 API（`engine/filter/llm_client.py`），pre_filter 用 `gpt-4o-mini`，scoring 用 `gpt-4o`，均在 `.env` 配置

## 开发命令

```bash
# 环境
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 完整流水线（验证改动）
python -m engine.cli -d elderly-care pipe

# 单步执行
python -m engine.cli -d elderly-care fetch      # 采集
python -m engine.cli -d elderly-care filter      # LLM 筛选
python -m engine.cli -d elderly-care report      # 生成日报
python -m engine.cli -d elderly-care api         # 启动 API (端口 8900)

# 进化分析
python -m engine.cli -d elderly-care evolve all     # 运行全部进化分析
python -m engine.cli -d elderly-care evolve sources  # 信源质量报告

# 详细日志
python -m engine.cli -v -d elderly-care fetch
```

## 环境配置

`.env` 文件（前缀 `INTEL_`）：
- `INTEL_LLM_BASE_URL` — LLM API 地址
- `INTEL_LLM_API_KEY` — API Key
- `INTEL_LLM_PRE_FILTER_MODEL` — 预筛模型（默认 gpt-4o-mini）
- `INTEL_LLM_SCORING_MODEL` — 评分模型（默认 gpt-4o）
- `INTEL_DB_PATH` — SQLite 路径（默认 data/intel.db）

## 添加新领域

在 `domains/<name>/` 下创建 6 个文件即可，引擎代码无需修改：
1. `sources.yaml` — 信源配置（必填字段：id, name, kind, url）
2. `categories.yaml` — 分类体系，每个分类有独立 `freshness_days`
3. `keywords.yaml` — 关键词列表（供 `keywords_filter: true` 的信源使用）
4. `scoring.md` — LLM 评分 system prompt
5. `pre_filter.md` — LLM 预筛 system prompt
6. `web/index.html` — 前端面板

## 添加新信源

在 `domains/<name>/sources.yaml` 的 `sources:` 列表中追加：
```yaml
- id: new_source
  name: 名称
  kind: rss          # rss / web / ageclub / searxng
  url: https://...
  tier: T1           # T1(必须) / T1.5(重要) / T2(参考)
  lang: zh           # zh / en / ja / fr
  keywords_filter: false
  tags: [标签]
```

## API 端点

```
GET /api/items?domain=elderly-care&mode=selected&days=3
GET /api/categories?domain=elderly-care
GET /api/sources?domain=elderly-care
GET /api/stats?domain=elderly-care
GET /api/trending?domain=elderly-care
GET /api/report/{date}?domain=elderly-care
GET /rss/curated?domain=elderly-care
GET /skill/{skill_name}/SKILL.md
```

## 代码风格

- Python 3.11+，使用 `from __future__ import annotations`
- 类型注解用 `X | None` 而非 `Optional[X]`（除与 Pydantic 兼容外）
- LLM prompt 修改在 `domains/<name>/scoring.md` 和 `pre_filter.md`
- 前端模板在 `domains/<name>/web/index.html`

## 常见任务

**测试单个信源采集：**
```bash
python3 -c "
from engine.fetcher.rss_fetcher import fetch_rss
from engine.models import SourceDef, SourceKind
s = SourceDef(id='test', name='test', kind=SourceKind.RSS, url='https://example.com/feed', lang='zh')
items = fetch_rss(s)
print(f'{len(items)} items')
"
```

**查看数据库统计：**
```bash
python3 -c "
from engine.store import Store
s = Store()
rows = s.conn.execute('SELECT source_id, COUNT(*) FROM raw_items GROUP BY source_id').fetchall()
for r in rows: print(f'{r[0]}: {r[1]}')
"
```
