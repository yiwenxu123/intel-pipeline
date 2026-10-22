# Intel Pipeline 优化执行计划（2026 Q4）

> 状态：ACTIVE  
> 建立：2026-10-22  
> 负责人：你（产品/编辑/拍板） + AI Agent（开发/分析）  
> 最近更新：2026-10-22  
> 下次复盘：2026-10-29（周四）  
> 唯一执行口径：本文件。`PRODUCT_PLAN.md`、`OPTIMIZATION_PLAN.md`、`INTERNAL_PRODUCT_ROADMAP.md`、`规划.md` 只作历史参考，不再作为执行依据。

---

## 0. 一句话方向

**养老继续用 intel-pipeline，但收缩成“内容选题供给”；AI 用 AIHOT + Hermes；历史用 Hermes 的编辑型采集；content-ops 是信号 hub。不把 intel-pipeline 做成万能引擎。**

三条边界：

1. 只做“采集 → 初筛 → 结构化 → 信号/日报”，不做写作、发布、多租户平台。
2. 新领域必须带 domain pack（信源、taxonomy、评分、账号、金标、评测），否则不上线。
3. 任何新功能先回答“它让哪条信号更容易被采用”，答不上来就不做。

---

## 1. 现状基线（2026-10-22 实测）

### 1.1 Windows 生产链路

| 指标 | 当前值 | 说明 |
|---|---|---|
| API 健康 | `/health` 正常 | 之前 Panorama 简报里的“8900 不可达”是旧状态/缓存 |
| 累计采集 | 9,255 条 | `/api/stats` |
| 累计精选 | 2,285 条 | score >= 5.5 |
| 待评分积压 | 0 | 正常 |
| 最近采集 | 2026-10-22 09:20 | 每小时任务在跑 |
| 最近 pipe | 2026-10-22 01:01，71.7s | 成功 |
| 采集失败信源 | 0 | 正常 |
| DB 大小 | 48.09 MB | 单机 SQLite |
| 本月 LLM 成本 | ¥32.81 | 成本很低 |
| 今日精选 | 4 条 | `/api/overview`，截至查询时 |
| 本周叙事 | “本周精选 3 条，较上周 ↑50%” | 与日报“本周 75 条，较上周 ↓39%”冲突，见 W0-03 |
| 简报覆盖率 | 68.5% | 低于 80% 目标，见 W2-06 |
| 反馈（7 天） | 0 条 | 反馈功能没有真实使用 |

### 1.2 API 真实可用性

- 轻查询正常：`/health`、`/api/stats`、`/api/overview`。
- Mac 上重查询超时，但 Windows `data/api.log` 显示同一批请求返回 200；根因是 Mac ZeroTier 直连路径丢包（1200/1400 字节 ping 分别为 50%/100% 丢包），不是 API 服务慢。
- 结论：**API 服务本身正常；Mac 大响应链路不可靠。** SSH 已改走腾讯云 ProxyJump；HTTP 大响应仍需隧道/LAN。暂不作为可靠交付面，冻结决策不变。

### 1.3 Hermes / 三账号

| 账号 | 领域 | 10-22 原始 → 过滤 → 信号 | 实际来源 | 观察 |
|---|---|---|---|---|
| 小白学AI | AI 工具/效率 | 83 → 48 → 20 | Tavily 9、GitHub 7、RSSHub 3、热榜 1 | 配置了 AIHOT，但最近 7 天没有 `source=aihot` |
| 无龄生命 | 银发经济 | 100 → 28 → 20 | AgeClub 14、RSSHub 6 | 与 intel-pipeline 存在重复采集 |
| 潘哆啦 | 历史/冷知识 | 41 → 3 → 3 | Orio 2、RSSHub 1 | 含百度知道/百度经验垃圾；瓶颈是编辑与核查 |

补充：Hermes 的 `content-theme-finder` 已经是一个“采集 + 过滤 + 聚类 + 选题”的编辑层；2026-10-22 已确认腾讯云容器内没有 `aihot_collector.py`，最近 signals 也没有 `source=aihot`，AIHOT 当前未贡献。

### 1.4 下游 content-ops

- signals 2,938 条；intel-pipeline 的 elderly-care 约 459 条（15.6%）。
- 40.3% 被选题引用；432 条 pending；约 60% 信号从未被引用（2026-10-17 审计）。
- 结论：**供给不是瓶颈，选题/成稿才是。** 新增采集器不会自动增加产出。

### 1.5 Panorama MCP

- 已安装到 Qoder：serverName `panorama`，serverId `46deda1e-eaf1-4c15-afd6-dbc35c66109d`，状态 `ready`，13 个工具。
- 启动命令：
  ```bash
  /Users/yiwenxu123/Projects/ai-agents/panorama/.venv/bin/python -c \
    "import sys, os; sys.path.insert(0, os.path.expanduser('~/.ai')); from panorama.serve import run; run()"
  ```
- 当前会话未热加载 `mcp__panorama__*`；新开会话应可见。可用工具：`read_env`、`list_skills`、`get_skill`、`nodes_health`、`daily_brief`、`health`、`workflow`、`actions_list` 等。
- 已用它确认：本机/腾讯云/Windows 三端在线；Windows 的 8900 状态 ok；Panorama Dashboard 正常运行。

---

## 2. 目标与指标

### 2.1 North Star

**每周被内容系统采用的信号数 / 由信号产生的可用选题数。**

不再用“采集条数”“精选率”“Dashboard 访问量”作为主指标。

### 2.2 目标

| 领域 | 指标 | 当前 | 目标（12 周） |
|---|---|---|---|
| 养老 | 每周被选题引擎采用的信号 | 未统计 | >= 10 |
| 养老 | precision@20（人工抽检前 20 条可用比例） | 未测 | >= 70% |
| 养老 | 简报字段覆盖率 | 68.5% | >= 85% |
| 养老 | 启用信源数 | 46 | 15–20 |
| 养老 | 零精选信源 | 3 | <= 1 |
| 养老 | 通用医疗/无关海外内容占比 | 偏高（约六成海外源） | < 20% |
| AI | 新领域上线时间 | 未量化 | < 2 天 |
| AI | precision@20 | 未测 | >= 70% |
| AI | 每周可用选题 | 未量化 | 8–10 |
| AI | AIHOT 日贡献 | 0（最近 7 天） | >= 5 条/天，或明确放弃 |
| 历史 | 每周可用且已核实选题 | 未量化 | 2–3 |
| 历史 | 抽样 10 条事实错误 | 未测 | 0 |
| 历史 | 跨日重复题材 | 存在（宋朝外卖案例） | 0 |
| 运维 | 7 日 pipe 成功率 | 当前正常 | >= 98% |
| 运维 | 08:00 前无数据告警 | 无 | 必须有 |
| 成本 | 月 LLM 成本 | ¥32.81 | < ¥100 |
| 维护 | 每周人工维护 | 未统计 | < 30 分钟 |

### 2.3 范围护栏（明确不做）

- 不做 Dashboard 重设计、React 重写、移动端。
- 不做对外 API 平台、多租户、登录/权限体系。
- 不做自动关键词/评分进化；所有自动修改配置必须有人确认。
- 不加新领域，除非先有 domain pack + 100 条金标 + 2 周评测。
- 不加新信源，除非先有产出率证据。
- 不增加第 8 个输出面；现有 JSON + Markdown + 飞书足够。

---

## 3. 工作流总览

| 工作流 | 目标 | 优先级 | 负责人 |
|---|---|---|---|
| W0 事实与可观测 | 先让数据可信、API 行为可解释 | P0 | AI + 你 |
| W1 信号契约与路由 | 让三个 producer 说同一种语言 | P0 | AI + 你 |
| W2 养老质量 | 从“有信号”到“可选题” | P0 | 你 + AI |
| W3 AI 试点 | 用现有 AIHOT/Hermes 做第二个真实领域 | P1 | 你 + AI |
| W4 历史试点 | 把历史当编辑/核查问题，不当新闻采集 | P2 | 你 + AI |
| W5 产品面收缩 | 删除没有用户的功能面 | P1 | AI |
| W6 运维与成本 | 单调度、可恢复、有告警 | P1 | AI + 你 |

状态图例：`TODO` 未开始 / `DOING` 进行中 / `BLOCKED` 被阻塞 / `DONE` 完成 / `DROPPED` 决定不做。  
工作量：`S` <= 0.5 天 / `M` 1–2 天 / `L` 3–5 天。

---

## 4. 详细任务

### W0 事实与可观测（P0）

| ID | 任务 | 工作量 | 负责人 | 依赖 | 验收标准 | 状态 |
|---|---|---|---|---|---|---|
| W0-00 | 现状复核：API、DB、Hermes、content-ops、Panorama | S | AI | — | 基线数字写入本文件 | DONE 2026-10-22 |
| W0-01 | 安装 Panorama MCP 并验证 13 个工具 | S | AI | — | server ready；新会话可见 `mcp__panorama__*` | DONE 2026-10-22（13 tools 已可见，read_env 验证通过） |
| W0-02 | API 重查询性能诊断：定位 SQLite 锁/单 worker/大字段序列化 | M | AI | W0-00 | `/api/items?days=2&take=50` p95 < 3s，或正式决定冻结并移出产品面 | DONE 2026-10-22（query plan TEMP B-TREE；加索引；SSH 隧道实测 `/api/items` 200/44KB；Mac 直连 ZeroTier 丢包是主因；API 因无真实用户继续冻结） |
| W0-03 | 统一“本周精选”口径：overview 与日报必须同源 | S | AI | W0-00 | 同一时刻两个入口数字一致；加一条回归检查 | DONE 2026-10-22（overview 与日报改用同一 weekly 数据，测试覆盖） |
| W0-04 | 修正 `/api/stats?date=` 忽略日期的问题 | S | AI | — | 传 date 返回当日数据，或删除该参数并更新文档 | DROPPED（API 冻结，不再投资） |
| W0-05 | 数据新鲜度/无数据告警 | S | AI | — | 08:00 前无新数据、或 last_fetch 超阈值时告警 | DONE 2026-10-22（freshness CLI + 08:00 任务；Windows smoke 正常） |
| W0-06 | 备份/恢复演练 | S | 你 + AI | — | 10 分钟内完成一次恢复并校验条数 | TODO |

### W1 信号契约与路由（P0）

| ID | 任务 | 工作量 | 负责人 | 依赖 | 验收标准 | 状态 |
|---|---|---|---|---|---|---|
| W1-01 | 定义 Signal Schema v1 | M | 你 + AI | — | 一份 schema + 示例；intel-pipeline/Hermes/content-ops 三端通过校验 | DOING 2026-10-22（schema + intel-pipeline 导出已落；Hermes/content-ops 校验待做） |
| W1-02 | 下游标题优先中文 | S | AI | W1-01 | 有中文翻译的条目 100% 优先 `title_zh`；无翻译时保留 `title_original` 并标记 `language`；部署后测覆盖率 | DONE 2026-10-22（生产导出 46/46 有 title_zh） |
| W1-03 | 项目/账号路由 | M | AI | W1-01 | `project_id`/`account_id` 可路由；两个项目互不串数据 | TODO |
| W1-04 | 去重与 `event_id` | M | AI | W1-01 | 重复率 < 2%；同一事件日报只出现一次 | TODO |
| W1-05 | 溯源与评分拆分 | S | AI | W1-01 | 下游可按 `source_tier`/`score_breakdown` 过滤 | TODO |

建议字段：

```json
{
  "project_id": "wulingshengming",
  "account_id": "wulingshengming",
  "domain": "elderly-care",
  "title_zh": "中文标题",
  "title_original": "原文标题",
  "language": "zh",
  "url": "https://...",
  "source_id": "ageclub_web",
  "source_tier": "T1",
  "published": "2026-10-22T00:00:00+08:00",
  "summary": "中文摘要",
  "key_points": ["..."],
  "score": 8.2,
  "score_breakdown": {"impact": 9, "evidence": 8, "fit": 8, "freshness": 7, "potential": 9},
  "category": "policy",
  "tags": ["长护险"],
  "entities": ["民政部"],
  "event_id": "evt_...",
  "content_type": "policy",
  "fact_check_status": null
}
```

### W2 养老质量（P0）

| ID | 任务 | 工作量 | 负责人 | 依赖 | 验收标准 | 状态 |
|---|---|---|---|---|---|---|
| W2-01 | 建立养老金标集 100–200 条 | M | 你 + AI | — | 含“政策相关 vs 通用医疗噪音”难例；标注 select/reject | DONE 2026-10-22（v2 金标 33 select/61 reject/6 either；P/R/F1 59.0/69.7/63.9，Top20 65%） |
| W2-02 | 评分标准 v2：从“行业决策”改为“内容可用” | M | 你 + AI | W2-01 | 五轴 + 内容类型权重 + 噪声上限；金标 precision@20 >= 70% | DOING 2026-10-22（Ark 评测：5.5→P91.3/R63.6；5.0→P87.1/R81.8/Top20 95%；待 holdout 与上线决策） |
| W2-02a | 新 holdout 50–100 条，验证 v2 + 5.0 门槛 | M | 你 + AI | W2-02 | 新样本上 P>=70%、Top20>=70%；不与开发集混用 | TODO |
| W2-03 | 双次评分 + 信源分级门槛 | M | AI | W2-02 | 两次独立评分取平均；T1/T1.5/T2 分门槛；成本 < ¥100/月 | TODO |
| W2-04 | 事件聚簇 + 一事件一条 | M | AI | W1-04 | 抽 10 个事件，日报 Top10 无同事件重复 | TODO |
| W2-05 | 信源组合清理 | S | 你 + AI | W2-01 | 启用 15–20 个；零精选 <= 1；日精选 15–25 条 | TODO |
| W2-06 | 日报 v2 | S | AI | W2-02 | 中文分类/来源名；Top5 附内容角度与 why now；统计口径正确 | TODO |

评分五轴建议（养老版，不照抄 AIHOT）：

1. **影响面**：政策/经营/用户影响多大。
2. **证据强度**：是否有文件号、金额、机构、时间、数据。
3. **受众匹配**：无龄生命读者是否关心。
4. **时效性**：现在写是否有意义。
5. **内容潜力**：是否有故事、反差、案例、可延展角度。

### W3 AI 试点（P1）

| ID | 任务 | 工作量 | 负责人 | 依赖 | 验收标准 | 状态 |
|---|---|---|---|---|---|---|
| W3-01 | 核实 AIHOT collector | S | AI | — | 容器内 `.py` 存在且运行，或明确移除配置；最近 7 天出现 `source=aihot` | DONE 2026-10-22（确认缺失：容器无 .py；最近 signals 无 aihot；配置仍在） |
| W3-01a | 恢复最小 AIHOT collector 或移除配置 | S | AI | W3-01 | 本地可跑通；用户确认后同步到容器 | DONE 2026-10-22（aihot.news collector；48h 50 条；过滤通知；AIHOT_AVAILABLE=True） |
| W3-02 | AI domain pack | M | 你 + AI | W1-01 | 信源/taxonomy/评分/账号/100 条金标齐全 | TODO |
| W3-03 | AI 两周试点（AIHOT + Hermes，不写新引擎） | M | 你 + AI | W3-01a/02 | 上线 < 2 天；precision@20 >= 70%；8–10 可用选题/周 | DOING 2026-10-22（窗口 10-23–11-05；基线已记录；每日摘要脚本就绪） |
| W3-04 | AIHOT 自建 vs 消费 feed 决策 | S | 你 | W3-03 | 一页决策：成本、源控制、维护量 | DONE 2026-10-22（先消费 feed，2 周后复盘） |

### W4 历史试点（P2）

| ID | 任务 | 工作量 | 负责人 | 依赖 | 验收标准 | 状态 |
|---|---|---|---|---|---|---|
| W4-01 | 历史素材 schema | S | AI | W1-01 | citation/source_type/fact_check_status/narrative_hook 字段 + 20 条示例 | TODO |
| W4-02 | 历史信源与噪声规则 | S | 你 + AI | — | 可信源清单；百度知道/经验、小说站、伪史站黑名单；抽 20 条噪声 < 20% | TODO |
| W4-03 | 历史两周试点（素材库 + 核查，不做高频采集） | M | 你 + AI | W4-01/02 | 50–100 条已核实素材；2–3 可用选题/周；抽 10 条 0 事实错误 | TODO |
| W4-04 | 历史是否需要 collector 的决策 | S | 你 | W4-03 | 若未达标，保留编辑型流程，停止采集投入 | TODO |

### W5 产品面收缩（P1）

| ID | 任务 | 工作量 | 负责人 | 依赖 | 验收标准 | 状态 |
|---|---|---|---|---|---|---|
| W5-01 | 冻结/删除 Dashboard、RSS、Skill | M | AI | W0-02 | 保留 `/health` + `/api/overview` 监控；无用户回归 | TODO |
| W5-02 | 关闭自动关键词/评分进化 | S | AI | — | 不再自动写 keywords.yaml / 注入 prompt；清理垃圾词 | DONE 2026-10-22（默认关闭；evolve all 只读；关键词 152→114） |
| W5-03 | china-africa 归档 | S | AI | — | 从调度/文档/产品叙事移除；保留模板 | DONE 2026-10-22（scheduler/README 归档；overview 过滤见 W5-03a） |
| W5-03a | overview 过滤已归档 domain | S | AI | W5-03 | `/api/overview` 不再显示 china-africa | DONE 2026-10-22（跳过 paused domains；测试覆盖） |
| W5-04 | 运营命令合并 | S | AI | — | 最多保留 quality-metrics / briefing-backfill 两个常用命令 | TODO |

### W6 运维与成本（P1）

| ID | 任务 | 工作量 | 负责人 | 依赖 | 验收标准 | 状态 |
|---|---|---|---|---|---|---|
| W6-00 | 修复 Mac→Windows SSH 路径 | S | AI | — | `ssh my-windows` 可用；不依赖直连 ZeroTier | DONE 2026-10-22（ProxyJump my-server；Windows sshd Running） |
| W6-01 | 单调度与跨机同步简化 | M | AI | — | 7 日成功率 >= 98%；无手动补跑 | TODO |
| W6-02 | 备份与恢复制度化 | S | 你 + AI | — | 每月一次，10 分钟内恢复 | TODO |
| W6-03 | LLM 成本预算与告警 | S | AI | — | 月成本 < ¥100；80% 时告警 | TODO |
| W6-04 | 周五 30 分钟复盘 | S | 你 | — | 连续 4 周更新本文件状态 | TODO |

### 4.1 第一周执行记录（2026-10-22）

| 任务 | 变更 | 验证 |
|---|---|---|
| W1-01 / W1-02 | `engine/ops/export_intel.py` 增加 schema v1、`title_zh`/`title_original`/`source_tier`/`project_id`/`account_id`；新增 `docs/SIGNAL_SCHEMA.md` | intel-pipeline 侧单测覆盖；Hermes/content-ops 适配待校验 |
| W0-03 | `engine/store.py` 增加 `_weekly_scored()`；overview 与日报共用同一周趋势数据 | 单测覆盖 narrative 与 weekly 一致 |
| W0-02 | 诊断：`ORDER BY score` 触发 TEMP B-TREE；新增 `idx_scored_domain_score`、`idx_raw_published` | 本地 query plan 确认；API 仍冻结，需下次重启生效 |
| W5-02 | `auto_evolution_enabled=False`；`evolve all` 只读；`evolve keywords` 默认只报告；清理 47 个碎片词 | `evolve all` 前后 keywords.yaml 哈希一致；211 tests passed |
| W5-03 | `scripts/scheduler.py` 移除 china-africa 调度；README 标记归档 | 无调度注册；文档更新 |
| W0-01 | Panorama MCP 注册并验证 | `mcp_list` 显示 13 个工具；`read_env` 调用成功 |
| SSH 修复 | `~/.ssh/config` 的 `my-windows` 增加 `ProxyJump my-server` | `ssh my-windows` 可登录；Windows `sshd` Running；直连 ZeroTier 1200/1400 ping 丢包 50%/100% |
| Windows 盘点 | Windows 10 19045；repo 在 `a9f1325`，本地 `keywords.yaml` +79 行；API-Boot 任务禁用，Hourly/Daily/Evolve 启用 | 已备份 `keywords.yaml.bak-20261022`；`git fetch` 显示落后 3 个提交 |
| API 路径复核 | SSH 隧道 18900→Windows 8900 | `/health` 200；`/api/items` 200/44KB；确认 API 正常，直连 ZeroTier 丢包 |
| Windows 部署 | Windows 拉取 `69c0eb0`；API-Boot 重新启用；API 重启为 PID 2620 | `/health` 200；导出 46 条，46/46 有 `title_zh`；keywords=114；auto_evolution=False |
| W5-03a | `/api/overview` 跳过 `paused_domains` | 单测覆盖；china-africa 不再出现在 overview |
| W2-01 工具 | 新增 `scripts/sample_gold_set.py` + `docs/GOLD_SET_GUIDE.md` | 生产生成 100 条（positive 26 / negative 24 / hard 50），另出 Excel 可读 CSV；待人工标注 |
| W3-01a | 恢复 Hermes `aihot_collector.py`，改用 `aihot.news` RSS；过滤 48 小时外和通知条目 | 容器测试 50 条，source=aihot，无通知；`AIHOT_AVAILABLE=True` |
| W3-03 启动 | 建立 7 天基线、14 天试点表、每日摘要脚本 `scripts/ai_pilot_summary.py` | 基线 83→48→20、3 选题；AIHOT-only 测试 50→50；首跑 10-23 03:00 |
| W0-05 | 新增 `ops freshness-check`、飞书告警、`run.bat freshness`、08:00 任务 | CLI 异常退出码 1；Windows smoke 正常；任务 Ready，下次 10-23 08:00 |
| W2-01 复核页 | 新增 `scripts/gold_review.html`，支持 JSONL 载入/1/2/3 判定/本地保存/导出 | 浏览器实测：100 条加载、判定与进度正常 |
| W2-01 标注 | 100 条人工标注完成；17 条 either 二次复核；专业复核 0083/0059/0081 | v2 金标 33 select/61 reject/6 either；P/R/F1 59.0/69.7/63.9，Top20 65% |
| W2-02 草案 | 新增 `domains/elderly-care/scoring_v2.md`、`scripts/eval_gold.py`；Ark Plan `deepseek-v4.1-flash` 跑完 100 条 | 5.5：P91.3/R63.6/Top20 95%；5.0：P87.1/R81.8/F1 84.4；in-sample，待 holdout |

**注意**：以上改动只在 Mac 工作区，尚未部署到 Windows。生产生效需要 `git pull` + 重启 API/定时任务；索引在 Store 初始化时自动创建。Windows 本地 `keywords.yaml` 的 79 行是旧自动进化留下的，部署前不要直接合并，先备份再显式丢弃或替换。

---

## 5. 90 天里程碑

| 里程碑 | 时间 | 交付 | 判断标准 |
|---|---|---|---|
| M0 事实与契约 | 10/22–10/28 | 基线、API 决策、Panorama MCP、Signal Schema、金标样本 50 条 | 数据可信；三端 schema 通过 |
| M1 养老质量 | 10/29–11/11 | 评分 v2、双评分、事件聚簇、信源清理、日报 v2 | precision@20 >= 70%；日精选 15–25 |
| M2 AI 试点 | 11/12–11/25 | AI domain pack、AIHOT/Hermes 试点、自建/消费决策 | 上线 < 2 天；8–10 选题/周 |
| M3 历史试点 | 11/26–12/09 | 历史素材库、噪声规则、两周试点 | 2–3 选题/周；0 事实错误 |
| M4 去留决策 | 12/10–12/23 | 是否抽共享层/是否合并 producer | 3+ 领域且 2+ 消费方才建 hub |
| M5 收尾 | 12/24–12/31 | 文档、交接、下季度计划 | 新人可按文档跑通 |

---

## 6. 追踪机制

### 6.1 每周五 30 分钟

1. 更新本文件所有 `DOING/BLOCKED` 状态。
2. 填一次指标：本周采用信号数、可用选题数、precision@20、编辑耗时、LLM 成本。
3. 只保留 3 个下周优先项；其他任务移到 `BACKLOG`。
4. 任何状态变更必须带证据：命令输出、文件链接、API 数字、样本数。

### 6.2 每月最后一个工作日 60 分钟

1. 对照第 2 节目标，判断 `继续 / 收缩 / 停止`。
2. 更新决策日志。
3. 清理已完成任务，归档到本文件末尾。

### 6.3 规则

- 没有证据的状态不算完成。
- 一个工作流同时最多 2 个 `DOING`。
- `BLOCKED` 超过 1 周必须升级：要么你拍板，要么删除任务。
- 新任务必须先说明它替代/删除了哪个旧任务，避免无限堆积。
- 旧计划文档不再更新；只更新本文件。

### 6.4 基础设施风险

- **Windows 10 19045 已不在主流支持期**：远程桌面看到的“升级 Win11”是系统级提示，不是 SSH 故障原因；是否升级另立计划，升级前先确认 n8n/DeerFlow/WeRSS/Intel 等兼容性。
- **API-Boot 定时任务已重新启用（2026-10-22 部署）**：API 已由任务重启为 PID 2620，`/health` 200；后续需确认开机自启。
- **Mac ZeroTier 直连 Windows 路径丢包**：SSH 已走 `ProxyJump my-server`；HTTP 大响应仍需隧道/LAN，不能再把“API 超时”误判为服务端慢。
- **Windows 本地 keywords.yaml 有 79 行自动生成碎片**：已备份 `keywords.yaml.bak-20261022`；部署时先备份，再显式丢弃或替换，不要 `git pull` 硬冲突。

---

## 7. 决策日志

| 日期 | 决策 | 原因 | 负责人 |
|---|---|---|---|
| 2026-10-22 | intel-pipeline 定位为“养老领域生产者”，不做万能引擎 | AI/历史采集范式不同；china-africa 证明复制文件夹不等于领域能力 | 你 + AI |
| 2026-10-22 | content-ops 作为 signals hub；intel-pipeline/Hermes/AIHOT 作为 producer | 已有 ADR-002 摄入层统一；避免重建平台 | 你 + AI |
| 2026-10-22 | AI 继续用 AIHOT + Hermes，不迁入 intel-pipeline | AIHOT 选择层更成熟；迁移是重复建设 | 你 + AI |
| 2026-10-22 | 历史按编辑/核查流程做，不做高频新闻采集 | 41→3 的产出说明瓶颈在编辑与事实核查 | 你 + AI |
| 2026-10-22 | Panorama MCP 安装到 Qoder | 后续用 read_env/nodes_health/daily_brief 做环境核对 | AI |
| 2026-10-22 | API 暂不作为可靠交付面；先诊断，默认冻结 | 重查询 15–60s 超时；真实消费者用 JSON/MD | 你 + AI |
| 2026-10-22 | API 正式冻结：保留 `/health` + `/api/overview` 监控 | 重查询不可用；不投入重写 | 你 + AI |
| 2026-10-22 | 养老评分转向“内容可用性” | 真实受众是内容选题，不是行业分析师 | 你 + AI |
| 2026-10-22 | AI 先消费 AIHOT feed，2 周后再决定自建 | 降低迁移风险，先验证贡献 | 你 + AI |
| 2026-10-22 | AIHOT collector 缺失，先恢复/移除配置再谈贡献 | 容器无 .py，最近 signals 无 aihot；配置与事实不符 | 你 + AI |
| 2026-10-22 | 恢复 AIHOT collector，使用 aihot.news RSS | 旧域名 2026-10-31 停用；容器测试 48h 50 条 | 你 + AI |

---

## 8. 明确不做 / 重新开启条件

| 不做 | 重新开启条件 |
|---|---|
| Dashboard 重设计 | 有 >= 2 个真实日活用户，且当前 Markdown 不能满足 |
| 对外 API 平台 | 有 >= 2 个外部 Agent/客户需要稳定查询，且文件契约不够 |
| 多租户/登录/权限 | 有外部客户或跨团队使用，且数据隔离是硬需求 |
| 自动关键词/评分进化 | 有金标评测证明自动改动优于人工确认 |
| 第三/第四个领域 | 现有 3 个领域都达到各自指标，且有明确 owner |
| 新信源 | 现有源产出率已测量，新源有 2 周试跑数据 |
| 移动端 | 有明确移动阅读需求，且日报/飞书不够 |
| 对外 SaaS | 先验证 5 个付费用户，另立产品，不在本仓库做 |

---

## 9. 第一周清单（2026-10-22 至 10-28）

| 日期 | 动作 | 产出 |
|---|---|---|
| 10-22 四 | 基线复核；安装 Panorama MCP；写本计划 | 本文件；MCP ready |
| 10-23 五 | W0-02 API 诊断；W0-03 周趋势口径；W1-01 schema 草稿 | API 决策；schema v1 |
| 10-24 六 | W1-02 中文标题；W5-02 关闭自动进化；W5-03 归档 china-africa | 下游标题修复；配置清理 |
| 10-25 日 | W2-01 金标样本 50 条 | 50 条标注 |
| 10-26 一 | W2-01 补到 100 条；W3-01 核实 AIHOT collector | 100 条金标；AIHOT 结论 |
| 10-27 二 | W2-02 评分标准草稿；W0-05 数据新鲜度告警 | rubric v0；告警 |
| 10-28 三 | 周复盘；更新状态；定下周 3 个优先项 | 更新后的本文件 |

**本周必须拍板的 3 件事：**

1. API：修到可用，还是冻结？默认冻结，除非有真实日活。
2. 养老评分：是否接受“内容可用性”替代“行业决策相关性”？
3. AI 领域：先消费 AIHOT feed，还是自建？默认先消费，2 周后再决定。

**已拍板（2026-10-22）**：1 冻结；2 接受；3 先消费 feed。

---

## 10. 关联文档

- 产品价值评估结论：见本文件第 0–2 节（2026-10-22 会话）
- Signal Schema：[SIGNAL_SCHEMA.md](./SIGNAL_SCHEMA.md)
- AI 试点追踪：[W3_AI_PILOT_2026-10-22.md](./W3_AI_PILOT_2026-10-22.md)
- 金标复核结果：[W2_GOLD_EVAL_2026-10-22.md](./W2_GOLD_EVAL_2026-10-22.md)
- [历史产品计划](./PRODUCT_PLAN.md)（仅历史参考）
- [历史优化计划](./OPTIMIZATION_PLAN.md)（仅历史参考）
- [内部产品路线图](./INTERNAL_PRODUCT_ROADMAP.md)（仅历史参考）
- content-ops 采集架构：[ADR-002](../../内容运营agent/docs/ADR-002-signal-collection-architecture.md)
- content-ops 数据审计：[数据流转审计](../../内容运营agent/docs/数据流转审计与本地稿件落盘评估-2026-10-17.md)
- Hermes 账号与信源：[accounts.yaml](../../hermes/hermes-sync/skills/content-theme-finder/config/accounts.yaml)
- AIHOT 参考：[README](https://github.com/KKKKhazix/AIHOT)、[精选与校准](https://github.com/KKKKhazix/AIHOT/blob/main/docs/selection.md)、[评分提示词](https://github.com/KKKKhazix/AIHOT/blob/main/industry/prompts/selection-score.md)

---

## 11. 更新记录

| 日期 | 更新人 | 内容 |
|---|---|---|
| 2026-10-22 | AI | 建立计划；写入实测基线；安装 Panorama MCP；确定 W0–W6 任务 |
| 2026-10-22 | AI | 完成 W0-01/02/03、W1-01（intel-pipeline 侧）/02、W3-01（确认 AIHOT 缺失）、W5-02/03；修复 Windows SSH（ProxyJump）；211 tests passed；改动文件 ruff 全绿 |
| 2026-10-22 | AI | 部署到 Windows：`69c0eb0`，API 重启 PID 2620，API-Boot 启用，导出 46/46 有 title_zh |
| 2026-10-22 | AI | 完成 W5-03a；新增 W2-01 抽样工具与标注指南；生产生成 100 条金标样本；恢复 AIHOT collector（aihot.news，48h 50 条）；启动 W3-03 AI 两周试点；完成 W0-05 新鲜度告警与复核页；金标专业复核完成；Ark Plan 评测 v2：5.5 P91.3/R63.6，5.0 P87.1/R81.8，Top20 95% |
