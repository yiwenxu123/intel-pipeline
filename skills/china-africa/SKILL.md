---
name: china-africa-intel
description: 中非经贸情报查询 Skill。当用户想知道中非经贸动态、投资合作、政策法规、贸易数据、风险预警等情报时使用。支持分类筛选、时间范围控制、关键词搜索。数据来自 intel-pipeline 引擎。
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

## 端点

Base URL: `http://localhost:8900`（`scripts/start.sh` 默认端口；自部署请替换）

**所有请求必须带 `domain=china-africa`。**

### 精选情报

```
GET /api/items?domain=china-africa&mode=selected&days=<N>&take=<N>&q=<关键词>
```

- `domain`: china-africa（必填）
- `days`: 1 / 3 / 7 / 30
- `take`: 最多 200（默认 50）
- `category`: policy / trade / investment / finance / tech_transfer / diplomacy / risk / case_study

### 全部情报

```
GET /api/items?domain=china-africa&mode=all&days=<N>&take=<N>
```

### 日报

```
GET /api/report/{YYYY-MM-DD}?domain=china-africa
```

### 统计与健康

```
GET /api/stats?domain=china-africa
GET /api/health?domain=china-africa
GET /api/trends?domain=china-africa&days=30
```

### RSS 订阅

- `/rss/curated?domain=china-africa` — 精选情报
- `/rss/all?domain=china-africa` — 全部情报
- `/rss/daily?domain=china-africa` — 今日日报

## 工作流

### 默认路径：拉精选

```bash
curl -s "http://localhost:8900/api/items?domain=china-africa&mode=selected&days=3&take=20"
```

### 按分类

```bash
curl -s "http://localhost:8900/api/items?domain=china-africa&mode=selected&category=investment&days=7"
```

### 关键词搜索

```bash
curl -s "http://localhost:8900/api/items?domain=china-africa&mode=selected&q=南非&days=7"
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
- 摘要是 LLM 生成的，引用前请回原文核对
- 默认走精选（mode=selected），只有用户明确说「全部」时才走 mode=all
- Dashboard：`http://localhost:8900/?domain=china-africa`
