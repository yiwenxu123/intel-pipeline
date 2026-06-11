[根目录](../../CLAUDE.md) > [engine](../) > **fetcher**

# fetcher — 采集层

## 模块职责

从 `sources.yaml` 定义的信源拉取原始情报，经关键词过滤、日期验证补全、URL 去重后写入 `raw_items`。**不做时间过滤**，保证历史数据完整入库。

## 入口与启动

- **调度入口**：`runner.py` → `fetch_all(domain, store, max_workers=4)`
- **调用方**：`engine/cli.py fetch`、`engine/pipeline.py` 第一阶段

## 信源 Fetcher 映射

| `SourceKind` | 实现文件 | 说明 |
|---|---|---|
| `rss` | `rss_fetcher.py` | feedparser 解析 RSS/Atom |
| `web` | `web_fetcher.py` | BeautifulSoup + CSS selectors |
| `searxng` | `searxng_fetcher.py` | SearXNG 元搜索 |
| `ageclub` | `ageclub_fetcher.py` | AgeClub 垂直站，提取原始来源 |

## 采集流水线（runner.py）

1. 并发采集所有 `enabled` 信源（`ThreadPoolExecutor`）
2. 可选关键词过滤（`source.keywords_filter` + `domain.keywords`）
3. `date_verifier.verify_dates_batch()` — 无日期条目从原文 HTTP 提取（上限 30 次）
4. `store.exists(url)` 去重 → `store.save_raw()`

**pipe 后处理**（非 runner 职责）：`pipeline.py` 对 score≥6 条目调用 `full_text_fetcher.fetch_and_extract()`，结果经 `store.update_full_text()` 写入。

## 对外接口

无 HTTP 接口；输出为 `FetchResult`（`new_items`、`errors`、`duration_seconds`）。

## 关键依赖与配置

- `httpx` — HTTP 请求
- `feedparser`、`beautifulsoup4`、`lxml` — 解析
- 信源级配置：`sources.yaml` 的 `kind`、`url`、`selectors`、`keywords_filter`、`enabled`

## 数据模型

输入：`SourceDef` → 输出：`RawItem`（`source_id`, `title`, `url`, `content`, `published`, `lang`, `extra`）

## 全文提取（full_text_fetcher.py）

- `extract_full_text(html)` — 密度算法从 HTML 提取正文（200–8000 字）
- `fetch_and_extract(url)` — HTTP 抓取 + 正文提取
- 由 `pipeline.py` 在筛选后并发调用（`max_workers=3`），非采集阶段

## 测试与质量

- `tests/test_fetcher.py` — RSS/web 采集、`_match_keywords`、`verify_dates_batch`、`full_text_fetcher`、`store.update_full_text`（mock HTTP，~20 cases）
- 辅助模块：`date_extractor.py`（日期正则）、`date_verifier.py`（批量验证）

## 常见问题 (FAQ)

**Q: 信源采集失败如何处理？**  
A: 错误记入 `FetchError`，不中断其他信源；CLI 展示失败表格。

**Q: 为何部分 web 信源 `enabled: false`？**  
A: JS 动态页面无法被静态 fetcher 抓取，需在 `sources.yaml` 注释说明替代信源。

## 相关文件清单

```
engine/fetcher/
├── runner.py           # 调度器（主入口）
├── rss_fetcher.py
├── web_fetcher.py
├── searxng_fetcher.py
├── ageclub_fetcher.py
├── date_verifier.py
├── date_extractor.py
└── full_text_fetcher.py  # 精选条目全文提取
```

## 常见修改场景

| 场景 | 修改位置 |
|---|---|
| 新增信源 kind | `models.py` SourceKind + 新 fetcher + `runner.py` 分支 |
| 调整关键词匹配规则 | `runner.py:_match_keywords` |
| 改进正文提取质量 | `full_text_fetcher.py` |
| 日期补全策略 | `date_verifier.py` / `date_extractor.py` |

## 变更记录 (Changelog)

- **2026-06-11**：新增 `full_text_fetcher` 文档与 `test_fetcher.py` 覆盖说明
- **2026-06-10**：init-architect 初始化
