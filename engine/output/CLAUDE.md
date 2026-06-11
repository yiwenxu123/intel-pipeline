[根目录](../../CLAUDE.md) > [engine](../) > **output**

# output — 输出层（API / 日报 / 推送）

## 模块职责

将 `scored_items` 对外暴露：REST API、RSS Feed、Web Dashboard、Markdown/JSON 日报，以及可选的 Webhook 推送。

## 入口与启动

| 入口 | 说明 |
|---|---|
| `api.py` → `start_api()` | Uvicorn 启动 FastAPI（默认 `0.0.0.0:8900`） |
| `report.py` → `generate_report()` / `save_report()` | CLI `report` 与 `pipe` 第三阶段 |
| `notifier.py` → `notify_report()` | 飞书/企微 Webhook 推送 |

## REST API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/items` | 条目列表（selected/all，支持 category/days/date/q） |
| GET | `/api/dates` | 有精选条目的日期导航 |
| GET | `/api/stats` | 采集/精选统计 |
| GET | `/api/categories` | 分类及条目数 |
| GET | `/api/sources` | 信源列表与状态 |
| GET | `/api/trending` | 热门标签/实体 |
| GET | `/api/report/{date}` | 指定日期日报 JSON |
| GET | `/api/evolution` | 进化分析摘要 |
| GET | `/api/health` | 健康检查 |
| POST | `/api/sources/{id}/confirm\|disable\|enable` | 信源生命周期管理 |
| GET | `/rss/curated`, `/rss/all`, `/rss/daily` | RSS Feed |
| GET | `/skill/{name}/SKILL.md` | Agent Skill 文档 |
| GET | `/` | Dashboard（`templates/dashboard.html`） |

**时间窗口逻辑**：`/api/items` 支持全局 `days` 覆盖，或按各分类 `freshness_days` 分别过滤。

## 日报生成

- 输出目录：`data/reports/`（`INTEL_REPORT_DIR`）
- 文件：`{date}-{domain}.md` + `.json`
- 内容：按分类分组，含评分、摘要、要点、标签

## 前端 Dashboard

- 模板路径：`engine/output/templates/dashboard.html`（**非** `domains/*/web/index.html`）
- 静态资源：`engine/output/static/`（离线 Tailwind：`tailwind.js` + `tailwind.min.css`），挂载于 `/static`
- API 托管于同一 FastAPI 进程，CORS 允许 GET

## 关键依赖与配置

- `fastapi`、`uvicorn`、`jinja2`
- `INTEL_API_HOST`、`INTEL_API_PORT`
- `INTEL_NOTIFY_WEBHOOK` — 留空则不推送

## 测试与质量

- `tests/test_api.py` — health、dashboard、stats、items、categories、sources、evolution、rss
- **缺口**：`notifier.py`、`report.py` 无独立单测

## 相关文件清单

```
engine/output/
├── api.py
├── report.py
├── notifier.py
├── static/           # tailwind.js, tailwind.min.css
└── templates/
    └── dashboard.html
```

## 常见修改场景

| 场景 | 修改位置 |
|---|---|
| 新增/修改 API 端点 | `api.py` |
| 调整 Dashboard UI | `templates/dashboard.html` + `static/` |
| 日报格式与模板 | `report.py` + 可选 `domains/*/daily_report.md` |
| 飞书/企微推送内容 | `notifier.py` + `INTEL_NOTIFY_WEBHOOK` |

## 变更记录 (Changelog)

- **2026-06-11**：补充 `static/` 离线 Tailwind 与常见修改场景
- **2026-06-10**：init-architect 初始化；明确 dashboard 位于 engine 非 domains
