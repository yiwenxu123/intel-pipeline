[根目录](../../CLAUDE.md) > [domains](../) > **china-africa**

# china-africa — 中非经贸情报领域

## 模块职责

覆盖中非双边政策、贸易动态、投资合作、金融货币、技术合作、外交关系、风险预警、案例观点。

## 配置文件

| 文件 | 说明 |
|---|---|
| `sources.yaml` | 21 个信源（政策、贸易、非洲媒体、国际组织等） |
| `categories.yaml` | 8 分类，各有独立 `freshness_days`（policy 30天，risk 3天等） |
| `keywords.yaml` | 中非经贸关键词（核心主题、政策外交、贸易投资、国别等） |
| `scoring.md` | 评分 prompt |
| `pre_filter.md` | 预筛 prompt（主路径未使用） |

## 分类体系（freshness_days）

| id | 名称 | 窗口 |
|---|---|---|
| policy | 政策法规 | 30 |
| trade | 贸易动态 | 7 |
| investment | 投资合作 | 14 |
| finance | 金融货币 | 7 |
| tech_transfer | 技术合作 | 14 |
| diplomacy | 外交关系 | 14 |
| risk | 风险预警 | 3 |
| case_study | 案例与观点 | 30 |

## 与 elderly-care 差异

- 信源规模较小（21 vs 54）
- 分类体系侧重贸易/投资/外交，无养老垂直源（无 `ageclub` kind）
- 数据库文件：`data/intel-china-africa.db`
- API 默认端口：8900（`scripts/start.sh` 映射）

## 运行状态：默认暂停

当前**非重点产品**，自动采集已暂停（`INTEL_PAUSED_DOMAINS=china-africa`）：

- scheduler 不注册本领域定时任务
- `start.sh` 默认不启动 8900 API
- 配置、数据库、Dashboard 均保留；需要时手动 `pipe` 即可

**恢复采集**：`.env` 中移除 `china-africa` → `./scripts/stop.sh && ./scripts/start.sh`

## 调度与端口（恢复后）

- **Scheduler**：8:30 采集+推送，14:00 仅采集（`scripts/scheduler.py`）
- **API 端口**：8900（`scripts/start.sh`）
- **数据库**：`data/intel-china-africa.db`

## 运行示例

```bash
python -m engine.cli -d china-africa pipe
python -m engine.cli -d china-africa evolve all
python -m engine.cli -d china-africa quality-review --take 20 --days 7
```

## 质量验收（上线后必做）

1. 连续运行 3 次 `pipe`（或依赖 scheduler 跑满 3 天）
2. `quality-review --take 20` 导出抽样，人工标记误报
3. 误报率 >20% 时调整 `scoring.md` 降分规则后重跑 `filter`

## Agent Skill

`skills/china-africa/SKILL.md` — 通过 API `/skill/china-africa/SKILL.md` 暴露

## 常见修改场景

| 场景 | 修改位置 |
|---|---|
| 扩展非洲本地媒体信源 | `sources.yaml` |
| 调整关键词覆盖范围 | `keywords.yaml` |
| 细化评分分类标准 | `scoring.md` |
| 政策类条目展示窗口 | `categories.yaml` policy.freshness_days |

## 待完善项

- [ ] 扩展信源覆盖更多非洲本地媒体与法语源
- [ ] 评估 SearXNG 热榜信源噪声比
- [ ] 完成首轮 quality-review 人工验收并记录误报率

## 变更记录 (Changelog)

- **2026-06-11**：Phase A — scoring.md 增降分规则与中非相关性判定；quality-review 验收流程
- **2026-06-11**：更新 keywords.yaml 已存在、categories 已配置 freshness_days
- **2026-06-10**：init-architect 初始化
