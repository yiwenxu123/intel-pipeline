---
name: elderly-care-intel
description: 养老/大健康情报查询 Skill。当用户想知道养老政策、银发经济、健康服务、智慧养老、养老金融等情报时使用。支持分类筛选、时间范围控制、关键词搜索。数据来自 intel-pipeline 引擎。
---

# 养老/大健康情报 Skill

让 Agent 用最自然的中文一句话拿到 intel-pipeline 引擎每日精编的养老/大健康情报。

## 什么时候用

| 用户在说 | 触发 |
|---|---|
| "今天养老有什么新闻"、"银发经济最新动态" | ✅ 触发 |
| "养老政策有什么变化"、"延迟退休最新消息" | ✅ 触发 |
| "智慧养老有什么新产品"、"适老化科技" | ✅ 触发 |
| "养老产业投资机会"、"银发经济市场数据" | ✅ 触发 |
| "最近一周的养老情报"、"最近3天养老动态" | ✅ 触发（时间范围） |

## 端点

Base URL: `http://localhost:8901`（`scripts/start.sh` 默认端口；自部署请替换）

### 精选情报

```
GET /api/items?domain=elderly-care&mode=selected&days=<N>&take=<N>&q=<关键词>
```

- `domain`: elderly-care（必填）
- `days`: 1 / 3 / 7 / 30（默认 3）
- `take`: 最多 200（默认 50）
- `q`: 关键词搜索（可选）
- `category`: 分类过滤（可选）

### 全部情报

```
GET /api/items?domain=elderly-care&mode=all&days=<N>&take=<N>
```

### 日报

```
GET /api/report/{YYYY-MM-DD}?domain=elderly-care
```

## 工作流

### 默认路径：拉精选

```bash
curl -s "http://localhost:8901/api/items?domain=elderly-care&mode=selected&days=3&take=20"
```

### 带时间范围

```bash
# 最近 24 小时
curl -s "http://localhost:8901/api/items?domain=elderly-care&mode=selected&days=1"

# 最近 7 天
curl -s "http://localhost:8901/api/items?domain=elderly-care&mode=selected&days=7"
```

### 按分类

```bash
# 分类：policy / industry / health_services / elderly_tech / finance_security / lifestyle / risk
curl -s "http://localhost:8901/api/items?domain=elderly-care&mode=selected&category=policy&days=7"
```

### 关键词搜索

```bash
curl -s "http://localhost:8901/api/items?domain=elderly-care&mode=selected&q=长期护理保险&days=7"
```

## 分类说明

| category slug | 中文说明 |
|---|---|
| policy | 政策法规 |
| industry | 行业动态 |
| health_services | 健康服务 |
| elderly_tech | 智慧养老 |
| finance_security | 养老金融 |
| lifestyle | 养老生活 |
| risk | 风险预警 |

## 注意事项

- API 匿名免费，无需 token
- 摘要是 LLM 生成的，引用前请回原文核对
- 默认走精选（mode=selected），只有用户明确说"全部"时才走 mode=all