---
name: intel-pipeline
description: 多领域行业情报引擎。当用户想了解银发产业、中非经贸等领域最新情报，或需要运行采集/筛选/日报流水线时使用。
---

# Intel Pipeline Skill

Intel Pipeline 是可插拔的垂直行业情报系统，当前支持 **elderly-care**（银发产业）和 **china-africa**（中非经贸）。

## 项目位置

本地开发路径示例：`~/Projects/intel-pipeline`（以实际部署为准）

## 多领域与端口

| 领域 | 说明 | API 端口（start.sh） |
|------|------|---------------------|
| `elderly-care` | 银发产业 | 8901 |
| `china-africa` | 中非经贸 | 8900 |

Dashboard：`http://localhost:<port>/?domain=<领域名>`

## 常用命令（macOS / Linux）

```bash
cd ~/Projects/intel-pipeline
source .venv/bin/activate

# 完整流水线（采集 → 筛选 → 全文 → 日报 → 进化 → 推送）
python -m engine.cli -d elderly-care pipe
python -m engine.cli -d china-africa pipe

# 单步
python -m engine.cli -d elderly-care fetch
python -m engine.cli -d elderly-care filter
python -m engine.cli -d elderly-care report

# 质量验收（新领域 / 调 prompt 后）
python -m engine.cli -d china-africa quality-review --take 20 --days 7

# 进化分析
python -m engine.cli -d elderly-care evolve all

# 启动 API + 调度器
./scripts/start.sh
```

## API 查询示例

```bash
# 银发产业精选（近 3 天）
curl -s "http://localhost:8901/api/items?domain=elderly-care&mode=selected&days=3&take=20"

# 中非经贸精选
curl -s "http://localhost:8900/api/items?domain=china-africa&mode=selected&days=7&take=20"

# 统计与健康
curl -s "http://localhost:8901/api/stats?domain=elderly-care"
curl -s "http://localhost:8901/api/health?domain=elderly-care"
```

## 环境变量（.env，前缀 INTEL_）

- `INTEL_LLM_BASE_URL` / `INTEL_LLM_API_KEY` — LLM API
- `INTEL_NOTIFY_WEBHOOK` — 飞书/企微推送（日报 + 管道告警）
- `INTEL_SCORE_WINDOW_DAYS` — 筛选窗口（默认 7）
- `INTEL_UNSCORED_WARN_THRESHOLD` — 待评分堆积告警阈值（默认 100）
- `INTEL_PIPE_ALERT_ERROR_THRESHOLD` — 采集失败告警阈值（默认 3）

## 领域 Skill 文档

- 银发产业：`skills/elderly-care/SKILL.md` 或 `GET /skill/elderly-care/SKILL.md`
- 中非经贸：`skills/china-africa/SKILL.md` 或 `GET /skill/china-africa/SKILL.md`
