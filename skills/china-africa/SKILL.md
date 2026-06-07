---
name: china-africa-intel
description: 中非经贸情报查询 Skill。当用户想知道中非经贸动态、投资合作、政策法规、贸易数据、风险预警等情报时使用。支持分类筛选、时间范围控制、关键词搜索。数据来自 intel-pipeline 引擎，实时从 20+ 信源采集、LLM 筛选。
---

# 中非经贸情报 Skill

让 Agent 用最自然的中文一句话拿到 intel-pipeline 引擎每日精编的中非经贸情报。

## 什么时候用

| 用户在说 | 触发 |
|---|---|
| "今天中非有什么新闻"、"最近中非动态" | ✅ 触发 |
| "非洲哪个国家投资机会多"、"中非贸易数据" | ✅ 触发 |
| "最近中非政策有什么变化"、"非洲风险预警" | ✅ 触发 |
| "帮我查一下安哥拉的投资信息" | ✅ 触发（关键词匹配） |
| "最近一周的中非经贸情报" | ✅ 触发（时间范围） |

## 先决条件

调 API 时需要带浏览器 User-Agent，否则可能被 403 拒绝：

```bash
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 intel-skill/0.1.0"
```

## 端点

Base URL: `https://intel-pipeline.local`（用户自部署）

### 精选情报

```
GET /api/items?mode=selected&days=<N>&take=<N>&q=<关键词>
```

- `days`: 1 / 3 / 7 / 30（默认 3，留空=3）
- `take`: 最多 200（默认 50）
- `q`: 关键词搜索（可选）
- `category`: 分类过滤（可选）

### 全部情报

```
GET /api/items?mode=all&days=<N>&take=<N>
```

### 日报

```
GET /api/report/{YYYY-MM-DD}
```

### RSS 订阅

- `/rss/curated` — 精选情报
- `/rss/all` — 全部情报
- `/rss/daily` — 今日日报

## 工作流

### 默认路径：拉精选（宽问题首选）

```bash
curl -sH "User-Agent: $UA" "https://intel-pipeline.local/api/items?mode=selected&days=3&take=20"
```

### 带时间范围

```bash
# 最近 24 小时
curl -sH "User-Agent: $UA" "https://intel-pipeline.local/api/items?mode=selected&days=1"

# 最近 7 天
curl -sH "User-Agent: $UA" "https://intel-pipeline.local/api/items?mode=selected&days=7"
```

### 按分类

```bash
# 分类选项: policy / trade / investment / finance / tech_transfer / diplomacy / risk / case_study
curl -sH "User-Agent: $UA" "https://intel-pipeline.local/api/items?mode=selected&category=investment&days=7"
```

### 关键词搜索

```bash
curl -sH "User-Agent: $UA" "https://intel-pipeline.local/api/items?mode=selected&q=南非&days=7"
```

### 拉日报

```bash
# 最新日报
curl -sH "User-Agent: $UA" "https://intel-pipeline.local/api/report/$(date +%Y-%m-%d)"
```

## 分类说明

| category slug | 中文 |
|---|---|
| policy | 政策法规 |
| trade | 贸易动态 |
| investment | 投资合作 |
| finance | 金融货币 |
| tech_transfer | 技术合作 |
| diplomacy | 外交关系 |
| risk | 风险预警 |
| case_study | 案例与观点 |

## 注意事项

- API 匿名免费，无需 token
- 限流 600 req/min/IP
- 摘要是 LLM 生成的，引用前请回原文核对
- 默认走精选（mode=selected），只有用户明确说"全部"时才走 mode=all
