[根目录](../../CLAUDE.md) > [engine](../) > **filter**

# filter — LLM 筛选层

## 模块职责

对 `raw_items` 中未评分的条目调用 LLM 批量评分，输出结构化 JSON（score、category、summary、tags 等），写入 `scored_items`。

## 入口与启动

- **主函数**：`pipeline.py` → `score_items(items, domain, batch_size=15)`
- **调用方**：`engine/cli.py filter`、`engine/pipeline.py` 第二阶段

## 评分流程

1. 将条目分批（默认 15 条/批）
2. 并行调用（`SCORE_MAX_PARALLEL=3` 线程池）
3. 每批构造 user prompt，system prompt 来自 `domains/<name>/scoring.md`
4. 可选注入：`scoring_injector.inject_calibration()` 追加校准指令
5. 解析 JSON 数组 → 组装 `ScoredItem`；结果不足时逐条重试

## 对外接口

| 模块 | 函数 | 说明 |
|---|---|---|
| `llm_client.py` | `chat(model, system, user)` | OpenAI 兼容 API 封装 |
| `llm_client.py` | `reset_usage()` / `get_usage()` | Token 用量追踪 |
| `pipeline.py` | `score_items()` | 批量评分主入口 |
| `pipeline.py` | `_parse_json_array()` | 容错 JSON 解析（有单测） |

## 关键依赖与配置

- `INTEL_LLM_BASE_URL`、`INTEL_LLM_API_KEY`
- `INTEL_LLM_SCORING_MODEL`（默认 `gpt-4o`）
- `INTEL_SCORE_WINDOW_DAYS`（默认 7）— 控制哪些 raw 条目进入评分
- `domain.scoring_prompt` — 领域评分 system prompt

## 数据模型

输入：`list[RawItem]` → 输出：`list[ScoredItem]` / `FilterResult`

## 测试与质量

- `tests/test_filter.py` — 覆盖 `_parse_json_array` 多种边界（markdown 代码块、尾逗号等）
- **缺口**：无 mock LLM 的 `score_items` 集成测试

## 设计说明

筛选编排见 `runner.py`：

```
正文补全 → 规则预筛(rule_prefilter) → LLM评分 → 质量闸门 → 简报提炼
```

- **LLM 预筛已废弃**（`pre_filter.md` / `pre_filter_items` 保留兼容，主路径不调用）
- **规则预筛**：零成本，被拒条目 `score=0` 入库，避免积压重复捞取
- **质量闸门**：合集降分、低输入封顶、事实锚点校验（`quality_gates.py`）

## 相关文件清单

```
engine/filter/
├── runner.py          # 筛选编排入口
├── rule_prefilter.py  # 规则预筛
├── enrichment.py      # 评分前正文补全
├── quality_gates.py   # 评分后闸门
├── briefing.py        # 精选后简报提炼
├── pipeline.py        # score_items, JSON 解析
└── llm_client.py  # OpenAI 客户端 + token 追踪
```

## 常见修改场景

| 场景 | 修改位置 |
|---|---|
| 调整评分 rubric / 分类标准 | `domains/<name>/scoring.md` |
| 修改批量大小或并发度 | `pipeline.py` 中 `batch_size` / `SCORE_MAX_PARALLEL` |
| 切换 LLM 模型 | `INTEL_LLM_SCORING_MODEL` 环境变量 |
| 注入评分校准指令 | `evolution/scoring_injector.py`（自动） |

## 变更记录 (Changelog)

- **2026-06-11**：补充常见修改场景表
- **2026-06-10**：init-architect 初始化；标注单轮评分现状
