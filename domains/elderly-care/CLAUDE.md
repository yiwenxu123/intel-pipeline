[根目录](../../CLAUDE.md) > [domains](../) > **elderly-care**

# elderly-care — 银发产业情报领域

## 模块职责

覆盖养老政策、银发经济、智慧养老、养老金融、健康服务、风险预警、养老生活等垂直情报。当前信源最丰富的主领域（54 个信源）。

## 配置文件

| 文件 | 说明 |
|---|---|
| `sources.yaml` | T1/T1.5/T2 分层信源：AgeClub、民政部、垂直媒体、SearXNG 搜索、海外源等 |
| `categories.yaml` | 7 分类，各有独立 `freshness_days`（policy 30天，risk 3天等） |
| `keywords.yaml` | 领域关键词，供 `keywords_filter: true` 信源使用 |
| `scoring.md` | 评分 prompt（含分类标准、打分 rubric） |
| `pre_filter.md` | 预筛 prompt（主路径未使用） |
| `EXTEND.md` | 领域扩展说明（非引擎加载） |

## 分类体系（freshness_days）

| id | 名称 | 窗口 |
|---|---|---|
| policy | 政策法规 | 30 |
| industry | 行业动态 | 7 |
| health_services | 健康服务 | 14 |
| elderly_tech | 智慧养老 | 7 |
| finance_security | 养老金融 | 14 |
| lifestyle | 养老生活 | 14 |
| risk | 风险预警 | 3 |

> 注：`sources.yaml` 中 `type: research` 为信源类型标签，非独立展示分类。

## 信源特点

- **垂直源**：`ageclub` kind 自动提取原始来源到 `extra.original_source`
- **政策源**：`type: policy`，lifecycle 不自动禁用
- **研究机构**：`type: research`，lifecycle 不自动禁用
- **热榜/搜索**：SearXNG + `keywords_filter: true` 控制噪声
- 部分 web 源 `enabled: false`（JS 动态页无法抓取，注释说明替代源）

## 调度与端口

- **Scheduler**：8:00 采集+推送，20:00 仅采集（`scripts/scheduler.py`）
- **API 端口**：8901（`scripts/start.sh`）
- **数据库**：`data/intel-elderly-care.db`

## 运行示例

```bash
python -m engine.cli -d elderly-care pipe
python -m engine.cli -d elderly-care evolve all
python -m engine.cli -d elderly-care quality-review --take 20
```

## Agent Skill

`skills/elderly-care/SKILL.md` — 通过 API `/skill/elderly-care/SKILL.md` 暴露

## 常见修改场景

| 场景 | 修改位置 |
|---|---|
| 新增养老垂直信源 | `sources.yaml`（参考 EXTEND.md） |
| 调整风险类展示窗口 | `categories.yaml` risk.freshness_days |
| 优化 SearXNG 噪声 | `keywords.yaml` + 信源 `keywords_filter` |
| 评分标准迭代 | `scoring.md`（evolution 可注入校准指令） |

## 变更记录 (Changelog)

- **2026-06-11**：修正分类数为 7（移除已不存在的 research 分类）；区分信源 type 与 category
- **2026-06-10**：init-architect 初始化
