# scripts/ — 运维脚本

> 启停、调度、状态检查。引擎逻辑在 `engine/`，领域配置在 `domains/`。

## 脚本一览

| 脚本 | 用途 |
|------|------|
| `start.sh` | 启动各领域 API + 调度器（后台） |
| `stop.sh` | 停止所有 API 与调度器 |
| `status.sh` | 查看 PID、端口、最近日志 |
| `scheduler.py` | APScheduler 定时 `pipe`（由 start.sh 拉起） |

## 端口映射

| 领域 | 端口 | Dashboard |
|------|------|-----------|
| elderly-care | 8901 | http://localhost:8901/?domain=elderly-care |
| china-africa | 8900 | http://localhost:8900/?domain=china-africa |

## 领域暂停（INTEL_PAUSED_DOMAINS）

非重点领域可暂停**自动采集**，不影响手动 CLI 与历史数据。

```bash
# .env
INTEL_PAUSED_DOMAINS=china-africa          # 默认已暂停中非
INTEL_PAUSED_DOMAINS=china-africa,foo      # 多领域逗号分隔
INTEL_PAUSED_DOMAINS=                        # 清空 = 全部恢复
```

暂停后行为：

- `scheduler.py`：不注册该领域定时任务；若任务已触发则直接跳过
- `start.sh`：不启动该领域 API（节省端口与进程）
- **仍可手动**：`python -m engine.cli -d china-africa pipe`

恢复中非经贸采集：

1. `.env` 中删除 `china-africa` 或设 `INTEL_PAUSED_DOMAINS=`
2. `./scripts/stop.sh && ./scripts/start.sh`
3. 可选：`python -m engine.cli -d china-africa pipe` 验证

## 调度计划

| 领域 | 时间 | 推送 |
|------|------|------|
| elderly-care | 08:00 | 是 |
| elderly-care | 20:00 | 否 |
| china-africa | 08:30 | 是（暂停时不注册） |
| china-africa | 14:00 | 否（暂停时不注册） |

## 常用命令

```bash
./scripts/start.sh                  # 全部非暂停领域（含 preflight 检查）
./scripts/start.sh elderly-care     # 仅银发产业
./scripts/status.sh                 # 含 quality-metrics 摘要
./scripts/stop.sh
./scripts/backup.sh                 # 备份 DB + domains

# 单独跑调度器（调试）
python scripts/scheduler.py
```

## CLI 运营命令

```bash
python -m engine.cli -d elderly-care quality-metrics
python -m engine.cli -d elderly-care ops digest-backlog --target 50
python -m engine.cli -d elderly-care briefing-backfill --limit 50
python -m engine.cli -d elderly-care ops weekly-report --notify
python -m engine.cli preflight
```

## 日志与 PID

- PID：`data/pids/api-<domain>.pid`、`data/pids/scheduler.pid`
- 日志：`data/logs/api-<domain>.log`、`data/logs/scheduler.log`

## 故障排查

| 现象 | 处理 |
|------|------|
| API 未启动 | `status.sh` 看 PID；查 `data/logs/api-*.log` |
| 定时未跑 | 确认 scheduler PID；查 `scheduler.log` |
| 某领域被跳过 | 检查 `INTEL_PAUSED_DOMAINS` |
| 端口占用 | `lsof -i :8901` 后 `stop.sh` 再 `start.sh` |
