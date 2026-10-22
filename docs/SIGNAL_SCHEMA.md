# Signal Schema v1

> 建立：2026-10-22  
> 生产者：intel-pipeline / Hermes / AIHOT  
> 消费者：content-ops `signals`、TopicEngine、Agent  
> 兼容：`schema_version = 1`；破坏性变更时升版本，不静默改字段含义。

## 目的

让不同采集引擎输出同一种“信号”，下游不再为每个引擎写一套适配器。  
`project_id` / `account_id` 为空表示旧版单项目模式；多项目场景由 producer 显式传入。

## 字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `schema_version` | int | 是 | 当前为 1 |
| `project_id` | string | 否 | 内容项目 ID；为空表示旧版单项目 |
| `account_id` | string | 否 | 账号 ID；为空表示未区分账号 |
| `domain` | string | 是 | `elderly-care` / `ai` / `history` 等 |
| `title` | string | 是 | 兼容别名：优先中文标题，没有则原文标题 |
| `title_zh` | string | 否 | LLM 生成的中文标题 |
| `title_original` | string | 否 | 原文标题 |
| `language` | string | 否 | `zh` / `en` / `ja` 等，来自信源或检测 |
| `url` | string | 是 | 原文链接 |
| `content` | string | 否 | 最佳正文：全文优先，其次 RSS 摘要 |
| `summary` | string | 否 | 中文摘要 |
| `key_points` | string[] | 否 | 2–4 条事实要点 |
| `score` | number | 是 | 0–10 或 0–100，按 producer 约定 |
| `score_breakdown` | object/null | 否 | 分轴评分；没有则 null |
| `category` | string | 否 | 领域分类 |
| `tags` | string[] | 否 | 标签 |
| `entities` | string[] | 否 | 实体 |
| `reason` | string | 否 | 对谁有用、怎么用 |
| `published` | string | 否 | ISO 时间或日期 |
| `source_id` | string | 是 | 信源 ID |
| `source_name` | string | 否 | 信源显示名 |
| `source_tier` | string | 否 | `T1` / `T1.5` / `T2` |
| `event_id` | string/null | 否 | 同一事件的聚簇 ID；没有则 null |
| `content_type` | string | 否 | `news` / `policy` / `report` / `analysis` / `research` / `opinion` |
| `fact_check_status` | string/null | 否 | 历史类必填：`verified` / `partial` / `unverified` |

## 示例

```json
{
  "schema_version": 1,
  "project_id": "wulingshengming",
  "account_id": "wulingshengming",
  "domain": "elderly-care",
  "title": "长期护理保险全国建制，养老服务商迎来三年订单窗口",
  "title_zh": "长期护理保险全国建制，养老服务商迎来三年订单窗口",
  "title_original": "长期护理保险全国建制，养老服务商迎来三年订单窗口",
  "language": "zh",
  "url": "https://example.com/a",
  "content": "正文……",
  "summary": "国家医保局发布……",
  "key_points": ["政策：……", "规模：……"],
  "score": 8.2,
  "score_breakdown": {"impact": 9, "evidence": 8, "fit": 8, "freshness": 7, "potential": 9},
  "category": "policy",
  "tags": ["长护险", "养老服务"],
  "entities": ["国家医保局"],
  "reason": "对养老机构运营者：……",
  "published": "2026-10-21T00:00:00+08:00",
  "source_id": "ageclub_web",
  "source_name": "AgeClub",
  "source_tier": "T1",
  "event_id": "evt_20261021_lcti",
  "content_type": "policy",
  "fact_check_status": null
}
```

## 消费方约定

1. 标题优先取 `title_zh`，其次 `title`，最后 `title_original`。
2. `title_zh` 为空时不要把英文标题直接当中文标题用；展示层应标注原文语言。
3. `event_id` 相同的信号在日报/选题池只保留一个代表条目，其余作为补充材料。
4. `source_tier` 用于排序或门槛，不用于替代内容质量判断。
5. 历史类信号必须带 `fact_check_status`；`unverified` 不得直接进入成稿。
6. 新增字段必须可选；删除/改名字段必须升 `schema_version`。

## 兼容策略

- intel-pipeline 的 `title` 已改为“中文优先”的兼容别名；旧消费方无需改动。
- 旧版 `intel-data.json` 没有 `title_zh`/`project_id`/`source_tier` 时，消费方按旧逻辑回退。
- `project_id`/`account_id` 为空时，content-ops 继续使用环境变量 `INTEL_PIPELINE_PROJECT` 的单项目模式。
