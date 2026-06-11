# Intel Pipeline 运营 SOP

## 每日操作（5 分钟）

1. **看 Dashboard**
   - 银发产业（主产品）：`http://localhost:8901/?domain=elderly-care`
   - 中非经贸：**默认已暂停自动采集**（`INTEL_PAUSED_DOMAINS=china-africa`）；需查看历史数据时手动 `start.sh china-africa` 或临时清空暂停配置
   - 顶部统计栏：采集时间绿/黄/红指示；**红色「N 信源失败」**需当日处理
   - 待评分：**≥100 条**标红（默认阈值 `INTEL_UNSCORED_WARN_THRESHOLD`），需运行 pipe 或缩小窗口
   - 日报 Tab：浏览今日精选，确认内容质量

2. **检查飞书推送**
   - 早间日报推送准时到达
   - **管道告警**（采集失败 ≥3 信源或阶段失败）会单独推送，与日报无关

3. **快速诊断**
   ```bash
   python -m engine.cli -d elderly-care report
   python -m engine.cli -d elderly-care evolve lifecycle
   # china-africa 暂停期间可跳过
   ```

## 每周操作（15 分钟）

1. **质量指标与验收**
   ```bash
   python -m engine.cli -d elderly-care quality-metrics
   python -m engine.cli -d elderly-care quality-review --take 20 --days 7
   ```
   误报率 > 20% 须当周调整 `scoring.md` 或 `rule_prefilter.py`。

2. **运营周报**（scheduler 周一 9:00 自动生成，亦可手动）
   ```bash
   python -m engine.cli -d elderly-care ops weekly-report --notify
   ```

3. **运行进化分析**
   ```bash
   python -m engine.cli -d elderly-care evolve all
   python -m engine.cli -d china-africa evolve all
   ```

2. **处理健康 Tab**
   - 最近采集 >24h → 检查 scheduler：`./scripts/status.sh`
   - 待评分超阈值 → `python -m engine.cli -d <domain> pipe`（或调 `INTEL_SCORE_WINDOW_DAYS`）
   - 低效信源 → 健康 Tab 禁用或确认

3. **关键词 staging**
   ```bash
   python -m engine.cli -d elderly-care evolve keywords
   ```
   有暂存建议时运行 `pipe` 自动验证。

## 备份

```bash
./scripts/backup.sh   # 数据库 + domains 配置
```

## API Token（写操作）

配置 `INTEL_API_TOKEN` 后，Dashboard 反馈需在浏览器控制台设置一次：

```javascript
localStorage.setItem('intel_api_token', '你的token');
```

## 积压消化

```bash
python -m engine.cli -d elderly-care ops digest-backlog --target 50
python -m engine.cli -d elderly-care briefing-backfill --limit 50
```

## 每月操作（30 分钟）

1. **评分校准**：审 `domains/<name>/scoring.md`，用 `quality-review` 抽样验收
2. **信源清单**：审 `sources.yaml`，`evolve sources` 看产出
3. **关键词**：`evolve keywords --apply`（已验证后）
4. **LLM 费用**：Dashboard 趋势 Tab 或 `GET /api/llm-usage?domain=...`（pipe 路径已持久化）
5. **数据库**：`ls -lh data/intel-*.db`；必要时 `VACUUM`

## 待评分堆积处理（A3）

| 堆积量 | 建议 |
|--------|------|
| < 50 | 正常，下次 pipe 自动消化 |
| 50–100 | 黄色预警，关注 scheduler |
| ≥ 100 | 红色告警：立即 `pipe` 或缩小 `INTEL_SCORE_WINDOW_DAYS` |

```bash
# 查看当前堆积
curl -s "http://localhost:8901/api/stats?domain=elderly-care" | python3 -m json.tool
```

## 新领域上线 CheckList

1. 复制 `domains/elderly-care/` → `domains/<new-name>/`
2. 配置 sources / categories / keywords / scoring.md
3. `python -m engine.cli -d <name> fetch` → `pipe`
4. `python -m engine.cli -d <name> quality-review --take 20` 人工验收
5. 添加 `scripts/scheduler.py` 任务 + `start.sh` 端口映射
6. 创建 `skills/<name>/SKILL.md`

## 故障处理

| 症状 | 排查 |
|------|------|
| 统计栏「尚未采集」 | 运行 `pipe`；检查 scheduler |
| 飞书收到管道告警 | 看健康 Tab 失败信源；`evolve sources` |
| 待评分飞书告警 | 运行 `pipe`；检查 `INTEL_UNSCORED_WARN_THRESHOLD` |
| LLM 失败 | 检查 `INTEL_LLM_*`；查看日志 |
| Dashboard 白屏 | `curl http://localhost:8900/health` |
