# Intel Pipeline 产品优化方案

> 基于 2026-06-08 全面代码审计制定，覆盖短期（Sprint 1-2）、中期（Sprint 3-5）、长期（Sprint 6+）三个阶段。
> 每个任务包含验收标准、涉及文件、依赖关系，可直接作为开发 checklist。

---

## 战略原则

1. **闭环优先于功能** — 先把已有功能的断点接上，再做新功能
2. **体验优先于功能** — 先让现有功能好用，再加新功能
3. **可观测优先于自动化** — 先让人能看到问题，再让系统自动处理
4. **单库多实例** — 代码库不拆分，每个领域独立部署实例（独立数据库、端口、定时任务）

---

## Sprint 1：基础设施加固（1-2 天）

> 目标：消除最高风险的技术债务，为后续所有迭代提供安全网。

### T1.1 数据库路径按领域隔离

**为什么现在做：** 当前 `db_path = "data/intel.db"` 是硬编码的，两个领域实例会写同一个库。这是独立部署方案的前置条件。

**改动范围：**
- `engine/config.py` — `db_path` 改为 `f"data/intel-{self.domain}.db"`

**验收标准：**
- [ ] `python -m engine.cli -d elderly-care fetch` 写入 `data/intel-elderly-care.db`
- [ ] `python -m engine.cli -d china-africa fetch` 写入 `data/intel-china-africa.db`
- [ ] 两个实例可以同时运行，互不干扰

**依赖：** 无
**预估：** 0.5 小时

---

### T1.2 Store 上下文管理器

**为什么现在做：** 当前 `Store()` 需要手动 `close()`，多处代码（尤其进化模块）存在连接泄漏风险。这是所有后续改动的基础。

**改动范围：**
- `engine/store.py` — 添加 `__enter__`/`__exit__`

**验收标准：**
- [ ] `with Store() as s:` 模式可用
- [ ] 现有代码中的 `store.close()` 调用改为 `with` 模式（渐进式，不必一次性改完）

**依赖：** 无
**预估：** 0.5 小时

---

### T1.3 搭建测试框架

**为什么现在做：** 2,550 行代码零测试。任何重构都是盲改。这是一切后续工作的安全网。

**改动范围：**
- 新建 `tests/` 目录
- `tests/test_store.py` — Store 层测试（CRUD、去重、查询）
- `tests/test_domain.py` — 领域配置加载测试
- `tests/test_filter.py` — filter pipeline 单元测试（mock LLM）
- `tests/conftest.py` — 共用 fixture（临时数据库、mock domain）

**验收标准：**
- [ ] `pytest` 可执行，所有测试通过
- [ ] Store 层测试覆盖：save_raw 去重、save_scored、get_selected 查询条件、get_stats
- [ ] Domain 层测试覆盖：load_domain、缺失配置报错、category_freshness 加载
- [ ] Filter pipeline 测试覆盖：pre_filter 解析、score_items JSON 解析、_parse_json_array 边界情况

**依赖：** T1.2
**预估：** 1 天

---

## Sprint 2：前端统一 + 体验基线（2-3 天）

> 目标：消除"开发者视角"最大的体验问题，统一前端架构。

### T2.1 统一前端模板（API 驱动）

**为什么现在做：** 两个领域有两套独立的前端代码，且架构不同（一个用 `window.__DATA`，一个用 `fetch API`）。统一后维护成本减半。

**改动范围：**
- 新建 `engine/output/templates/dashboard.html` — 通用模板
- `engine/output/api.py` — 修改 `index()` 路由，使用通用模板
- 删除 `domains/*/web/index.html`（或保留作为覆盖，通用模板优先）

**设计要点：**
- 通过 API `/api/items?domain=xxx` 加载数据，不再依赖 `window.__DATA`
- URL 参数 `?domain=elderly-care` 控制当前领域
- 分类标签、颜色映射从 API `/api/categories?domain=xxx` 动态加载，不在前端硬编码
- 保留 elderly-care 的多视图设计（精选/政策追踪/深度阅读），但通过 API 参数实现

**验收标准：**
- [ ] 访问 `http://localhost:8900/?domain=elderly-care` 显示银发产业面板
- [ ] 访问 `http://localhost:8900/?domain=china-africa` 显示中非经贸面板
- [ ] 精选/政策追踪/深度阅读 Tab 正常工作
- [ ] 分类筛选、信源筛选、搜索、时间范围均正常
- [ ] 两个领域的分类标签和颜色来自 API，不硬编码

**依赖：** T1.1
**预估：** 2 天

---

### T2.2 信源名称映射

**为什么现在做：** 侧边栏显示 `wx_guojiaminzheng`、`baidu_hot` 等 ID，这是"开发者产品"和"情报产品"的分界线。

**改动范围：**
- `engine/output/api.py` — `/api/items` 返回值增加 `source_name` 字段（从 DomainConfig 查找）
- 通用前端模板 — 信源列表和条目卡片显示 `source_name`，附带小字 `source_id`

**验收标准：**
- [ ] 侧边栏信源列表显示"国家民政养老服务"而非 `wx_guojiaminzheng`
- [ ] 条目卡片的来源显示信源名称
- [ ] 悬停/小字显示 source_id（方便排查）

**依赖：** T2.1
**预估：** 0.5 天

---

### T2.3 前端错误处理 + 加载状态

**为什么现在做：** 当前 API 挂了页面永远显示"加载中..."，没有错误提示。搜索无结果时没有区分"没有数据"和"正在加载"。

**改动范围：**
- 通用前端模板 — fetch 调用增加 try/catch、超时处理、错误状态展示

**验收标准：**
- [ ] API 不可达时显示"服务不可用"提示，而非无限加载
- [ ] 搜索无结果时显示"未找到匹配结果"而非"暂无数据"
- [ ] 数据加载中显示骨架屏（skeleton）而非纯文字
- [ ] 有重试按钮

**依赖：** T2.1
**预估：** 0.5 天

---

### T2.4 统计栏信息增强

**为什么现在做：** 当前统计栏只有"采集 N | 精选 M"，信息密度太低。

**改动范围：**
- `engine/output/api.py` — `/api/stats` 返回值增加：`select_rate`、`by_category`、`last_fetch_time`、`last_fetch_duration`
- 通用前端模板 — 统计栏展示更丰富的信息

**验收标准：**
- [ ] 统计栏显示：精选率（百分比）、最近采集时间、分类条数分布
- [ ] 数字格式化：大数加千分位（如 1,234）

**依赖：** T2.1
**预估：** 0.5 天

---

## Sprint 3：可观测性 + 错误可见化（1-2 天）

> 目标：从"黑盒"变成"可观测"，让用户信任系统。

### T3.1 采集错误报告

**为什么现在做：** 当前任何一个信源挂掉，用户只知道"采集完成：新增 0 条"，不知道为什么。这是影响系统可信度的 #1 问题。

**改动范围：**
- `engine/fetcher/runner.py` — `fetch_all()` 返回值改为 `FetchResult`（含 `new_items` + `errors`）
- `engine/cli.py` — fetch 命令展示失败信源列表及原因
- `engine/output/api.py` — `/api/stats` 增加 `last_fetch_errors` 字段

**新增模型：**
```python
class FetchError(BaseModel):
    source_id: str
    error: str
    error_type: str  # timeout / parse_error / http_error / unknown

class FetchResult(BaseModel):
    new_items: list[RawItem]
    errors: list[FetchError]
    duration_seconds: float
    sources_total: int
    sources_success: int
```

**验收标准：**
- [ ] `fetch` 命令输出中显示"成功 N 个源 / 失败 M 个源"
- [ ] 失败的源列出 source_id 和错误原因
- [ ] `/api/stats` 返回最近一次采集的错误列表
- [ ] Dashboard 统计栏显示采集健康状态（绿色/黄色/红色指示器）

**依赖：** T1.2
**预估：** 1 天

---

### T3.2 LLM 筛选进度增强

**为什么现在做：** 执行 `filter` 时信息不足，用户不知道 LLM 调用是否成功、耗时多少。

**改动范围：**
- `engine/filter/pipeline.py` — 返回值增加统计信息
- `engine/cli.py` — filter 命令结束时展示 Rich Panel 汇总

**验收标准：**
- [ ] filter 完成后显示：总耗时、LLM 调用次数、成功/失败条目数、平均每次调用延迟
- [ ] 预筛阶段显示"通过率"（通过/总数）
- [ ] 评分阶段显示每批的成功解析率

**依赖：** T1.3
**预估：** 0.5 天

---

### T3.3 Scheduler 改造

**为什么现在做：** 当前 `scheduler.py` 通过修改 `sys.argv` 来调用 CLI，这是 hack。而且无法获取管道执行结果，无法做健康检查。

**改动范围：**
- `scripts/scheduler.py` — 直接调用管道函数（fetch_all → pre_filter → score_items → generate_report），不经过 CLI
- 增加执行结果日志和错误捕获
- 支持配置不同领域的独立调度时间

**验收标准：**
- [ ] 不再依赖 `sys.argv` hack
- [ ] 每次执行后记录：耗时、采集数、筛选数、错误数
- [ ] 执行失败时记录完整错误堆栈

**依赖：** T3.1
**预估：** 0.5 天

---

## Sprint 4：进化闭环（2-3 天）

> 目标：把已有的 462 行进化代码从"死代码"变成"活功能"。

### T4.1 关键词建议可执行化

**为什么现在做：** `evolve keywords` 目前输出 Markdown 报告到 `data/reports/`，然后就没有然后了。应该变成可执行的建议。

**改动范围：**
- `engine/evolution/keyword_expander.py` — 新增 `suggest_keywords_diff()` 函数，输出可直接追加到 `keywords.yaml` 的 YAML diff
- `engine/cli.py` — `evolve keywords` 增加 `--apply` 参数，一键追加建议关键词
- 新增确认机制：列出将要添加的关键词，用户输入 y/n

**验收标准：**
- [ ] `evolve keywords` 默认只展示建议列表（不写入）
- [ ] `evolve keywords --apply` 展示 diff 并请求确认后，自动追加到 `keywords.yaml`
- [ ] 追加的关键词带注释标记（`# auto-suggested on 2026-06-08`）
- [ ] 重复关键词不会被追加

**依赖：** T1.3
**预估：** 1 天

---

### T4.2 信源健康自动标记

**为什么现在做：** `evolve sources` 输出的报告中已经标注了 `ineffective` 和 `dormant` 信源，但这些信息没有反馈到系统中。

**改动范围：**
- `engine/evolution/source_analyzer.py` — 新增 `get_unhealthy_sources()` 函数
- `engine/cli.py` — `evolve sources` 增加自动标记建议
- `engine/output/api.py` — `/api/sources` 返回值增加信源健康状态

**验收标准：**
- [ ] `evolve sources` 输出中明确标注"建议禁用"的信源
- [ ] `/api/sources` 返回每个信源的健康状态（healthy/low/ineffective/dormant）
- [ ] Dashboard 信源列表用颜色标识健康状态

**依赖：** T3.1
**预估：** 0.5 天

---

### T4.3 评分校准反馈

**为什么现在做：** `evolve scoring` 产出了评分分布分析，但没有给出可操作的建议。

**改动范围：**
- `engine/evolution/scoring_calibrator.py` — 新增 `suggest_adjustments()` 函数，输出具体的 prompt 调整建议
- `engine/cli.py` — `evolve scoring` 增加操作建议输出

**验收标准：**
- [ ] 评分报告中包含具体的 `scoring.md` prompt 调整建议
- [ ] 例如："分类 X 平均分 9.2，建议在 prompt 中增加'评分要严格，7分以上必须有具体数据支撑'的提示"
- [ ] 建议格式可直接复制粘贴到 `scoring.md`

**依赖：** T1.3
**预估：** 0.5 天

---

### T4.4 进化模块 API 化

**为什么现在做：** 进化分析目前只能通过 CLI 触发。Dashboard 应该能展示进化数据。

**改动范围：**
- `engine/output/api.py` — 新增 `/api/evolution?domain=xxx` 端点，返回信源健康、评分分布、关键词建议的结构化数据
- 通用前端模板 — 增加"系统健康"视图

**验收标准：**
- [ ] `/api/evolution` 返回：sources_health + scoring_distribution + keyword_suggestions
- [ ] Dashboard 新增 Tab 或侧边栏入口"系统健康"
- [ ] 展示信源健康列表、评分分布图（简单柱状图）、关键词建议列表

**依赖：** T4.1, T4.2, T4.3
**预估：** 1 天

---

## Sprint 5：推送 + 前端增强（1-2 天）

> 目标：从"人找信息"变成"信息找人"，提升使用频率。

### T5.1 每日情报推送

**为什么现在做：** 每天自动采集筛选后，用户需要主动打开 dashboard。推送让情报"送上门"。

**改动范围：**
- 新建 `engine/output/notifier.py` — 通知抽象层
- 新建 `engine/output/notifier_feishu.py` — 飞书 Webhook 实现
- `engine/config.py` — 新增 `INTEL_NOTIFY_WEBHOOK` 配置
- `scripts/scheduler.py` — 管道执行成功后自动推送

**推送内容设计：**
```
📊 银发产业情报日报 | 2026-06-08
采集 285 条 → 精选 18 条（精选率 6.3%）

🔴 热门：
1. [8.5] 民政部发布《养老服务条例》修订草案
2. [8.2] 泰康保险获 50 亿养老社区投资批文
3. [7.8] 日本介护报酬改革对中国市场的启示

📂 分类：政策法规 5 | 行业动态 6 | 智慧养老 3 | ...
🔗 查看完整报告 → http://10.207.251.137:8900
```

**验收标准：**
- [ ] 管道执行成功后，自动向 Webhook URL 发送摘要
- [ ] Webhook URL 未配置时不发送（不报错）
- [ ] 推送内容包含：精选数、精选率、Top 3 标题和分数、分类分布
- [ ] 推送失败不影响管道执行

**依赖：** T3.1
**预估：** 1 天

---

### T5.2 Dashboard Favicon + 页面标题

**为什么现在做：** 浏览器 tab 显示默认图标，页面标题在 API 模式下不更新。这些小问题积累起来影响专业感。

**改动范围：**
- 通用前端模板 — 增加 favicon（data URI 内嵌，不依赖外部文件）
- 页面标题从 API 动态获取

**验收标准：**
- [ ] 浏览器 tab 显示自定义图标
- [ ] 页面标题显示"银发产业情报 — Intel Pipeline"或"中非经贸情报 — Intel Pipeline"

**依赖：** T2.1
**预估：** 0.5 小时

---

### T5.3 条目卡片交互增强

**为什么现在做：** 当前条目卡片信息密度不够，用户需要点开链接才能看到更多内容。

**改动范围：**
- 通用前端模板 — 条目卡片增加展开/收起功能

**展开后显示：**
- 完整摘要（当前截断为 2 行）
- 完整 key_points 列表
- 完整推荐理由
- content_type 标识（新闻/政策/报告/分析/研究）

**验收标准：**
- [ ] 点击条目卡片（非链接区域）可展开/收起详情
- [ ] 展开状态有明显的视觉反馈
- [ ] 默认收起，只显示标题、分类、来源、摘要前 2 行

**依赖：** T2.1
**预估：** 0.5 天

---

## Sprint 6：长期优化（2 周+）

> 目标：为产品长期发展奠定基础。

### T6.1 Dashboard 趋势统计

**改动范围：**
- `engine/store.py` — 新增 `daily_stats` 表，记录每日统计快照
- `engine/cli.py` — `report` 命令同时写入统计快照
- `engine/output/api.py` — 新增 `/api/trends?domain=xxx&days=30` 端点
- 通用前端模板 — 趋势视图（Chart.js 折线图）

**统计维度：**
- 每日采集总数、精选总数、精选率
- 各分类的每日条目数变化
- 各信源的每日产出率变化

**依赖：** T2.1, T1.3
**预估：** 2 天

---

### T6.2 全文提取增强

**当前问题：** 大部分信源只采集到标题和摘要，深度阅读视图的内容很单薄。

**改动范围：**
- `engine/fetcher/web_fetcher.py` — 增加全文提取逻辑（readability 算法）
- 新建 `engine/fetcher/content_extractor.py` — 通用正文提取器
- `engine/models.py` — `RawItem` 增加 `full_content` 字段

**验收标准：**
- [ ] web 类型信源可提取正文
- [ ] RSS 类型信源对缺少 content 的条目自动抓取原文
- [ ] 存储时区分 `content`（摘要）和 `full_content`（全文）
- [ ] 深度阅读视图显示全文摘要

**依赖：** T1.3
**预估：** 2 天

---

### T6.3 LLM 成本追踪

**改动范围：**
- `engine/filter/llm_client.py` — 记录每次调用的 token 消耗
- `engine/store.py` — 新增 `llm_usage` 表
- `engine/output/api.py` — `/api/stats` 增加 LLM 成本数据

**验收标准：**
- [ ] 每次 LLM 调用记录：model、input_tokens、output_tokens、cost_estimate
- [ ] `/api/stats` 返回累计消耗
- [ ] CLI filter 命令结束时显示本次消耗

**依赖：** T3.2
**预估：** 1 天

---

### T6.4 LLM 响应解析健壮化

**当前问题：** `_parse_json_array()` 用 regex 提取 JSON，边界情况下会静默丢失数据。

**改动范围：**
- `engine/filter/pipeline.py` — `_parse_json_array` 增加重试和降级逻辑

**改进方案：**
1. 先尝试直接 JSON 解析
2. 失败则提取代码块中的 JSON
3. 失败则 regex 提取第一个 `[...]` 块
4. 全部失败 → 记录原始响应到日志，返回空列表（当前行为）
5. 对单条解析失败的条目，增加单条重试（重新发 LLM 请求，只发失败的那一条）

**依赖：** T1.3
**预估：** 1 天

---

## 不做的事情（明确排除）

| 功能 | 原因 |
|------|------|
| React/Vue 重写前端 | 当前体量不需要，inline JS + 模板化足够 |
| 微服务拆分 | 2,550 行代码拆微服务是过度工程 |
| 移动端适配 | 情报产品桌面使用为主 |
| 暗色模式 | 不影响核心功能 |
| 用户认证/权限 | 内网独立部署不需要 |
| 多租户 | 单库多实例已解决 |
| 自动化信源管理 | 进化模块输出建议即可，自动修改 sources.yaml 风险太高 |
| AI Agent 自主调度 | 当前信源固定，不需要智能调度 |
| 第三个领域 | 先把两个领域用好 |

---

## 依赖关系图

```
T1.1 数据库隔离 ──┐
T1.2 Store上下文 ──┼── T1.3 测试框架 ──┬── T4.1 关键词建议
                   │                   ├── T4.2 信源健康
                   │                   ├── T4.3 评分校准
                   │                   ├── T6.1 趋势统计
                   │                   ├── T6.2 全文提取
                   │                   └── T6.4 LLM解析健壮化
                   │
                   ├── T2.1 统一前端 ──┬── T2.2 信源名称
                   │                   ├── T2.3 错误处理
                   │                   ├── T2.4 统计增强
                   │                   ├── T5.2 Favicon
                   │                   └── T5.3 卡片增强
                   │
                   └── T3.1 错误报告 ──┬── T3.2 LLM进度
                                       ├── T3.3 Scheduler
                                       ├── T4.4 进化API
                                       └── T5.1 推送通知
```

---

## 每日执行建议

**Day 1：** T1.1 + T1.2 + T2.2（信源名称，0.5 天即可完成，立即提升体验）

**Day 2：** T2.1（统一前端，这是最大的单项工作）

**Day 3：** T2.3 + T2.4 + T5.2（前端体验完善）

**Day 4：** T1.3（测试框架）+ T3.1（采集错误报告）

**Day 5：** T3.2 + T3.3 + T5.1（可观测性 + 推送）

**Day 6-7：** T4.1 + T4.2 + T4.3 + T4.4（进化闭环）

**Day 8-9：** T5.3（卡片增强）+ T6.4（LLM 健壮化）

**Day 10+：** T6.1（趋势统计）+ T6.2（全文提取）+ T6.3（成本追踪）
