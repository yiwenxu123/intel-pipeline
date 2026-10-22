# 养老金标集标注指南（v0）

> 目的：用 100–200 条人工标注样本校准“内容可用性”评分，而不是凭感觉调 prompt。  
> 输出文件：`data/gold/elderly-care.jsonl`（`data/` 已被 gitignore，不提交）。

## 1. 抽样

Windows 生产库：

```powershell
.venv\Scripts\python.exe scripts\sample_gold_set.py --limit 100 --days 30
```

Mac 本地库（仅测试脚本）：

```bash
.venv/bin/python scripts/sample_gold_set.py \
  --db data/intel-elderly-care.db --limit 10 --days 10000 \
  --output /tmp/gold-test.jsonl
```

默认按 30 天、100 条、固定随机种子抽样，包含：

- `positive`：当前 score >= 5.5 的精选
- `negative`：低分或被规则拒绝的条目
- `hard`：4.5–6.5 的边界样本（最值得标）

## 2. 标注

推荐用本地复核页，不必手改 JSONL：

```bash
open scripts/gold_review.html
# 或浏览器打开 file:///.../intel-pipeline/scripts/gold_review.html
```

在页面里选择 `data/gold/elderly-care-20261022.jsonl`，然后：

- `1` = 可写（select）
- `2` = 不写（reject）
- `3` = 两可（either）
- `←` / `→` 前后切换；备注可选

标注会保存在浏览器 localStorage；完成后点“导出标注 JSONL”，把文件交回。  
`*-review.csv` 是给 Excel/Numbers 看的，复核页请用 JSONL。

## 3. 标注字段

每行 JSON 的 `gold`：

```json
{"decision": "", "notes": ""}
```

`decision` 只填三个值：

| 值 | 含义 |
|---|---|
| `select` | 值得进入无龄生命的选题候选；编辑会考虑写 |
| `reject` | 不值得；噪音、无关、无事实、不可用 |
| `either` | 两可，或信息不足；不计入准确率 |

`notes` 写一句理由，尤其是“为什么高分但不要”或“为什么低分但值得”。

## 4. 判断标准

先问四个问题：

1. 这条对无龄生命的读者（中老年及其子女、养老从业者）有关系吗？
2. 有没有可核验的事实：政策号、金额、机构、时间、数据？
3. 现在写有没有意义：新政策、新案例、新变化，而不是旧闻重发？
4. 有没有可写的角度：故事、反差、案例、可操作建议？

建议的取舍：

- 国家/地方养老政策、长护险、养老金、医保、养老服务监管：优先 `select`
- 具体企业/机构案例，有金额、模式、结果：优先 `select`
- 海外养老模式，能对中国有类比/借鉴：可 `select`，但注明“需要中国视角”
- 通用医学科研（小鼠实验、癌症医院建设、罕见病药物）、与老年无直接关系的新闻：`reject`
- 只有标题/摘要、没有事实锚点、无法核原文：`reject` 或 `either`
- 合集/快讯/多条事件打包：`reject`，除非其中有一条特别重要且可单独成题

注意：不要按“当前 score 高不高”来标；标注的是**内容本身是否值得选题**，不是复述模型结论。

## 5. 样本量与分层

- 第一版 100 条即可；目标是 200 条。
- 至少覆盖：政策、行业、健康服务、智慧养老、养老金融、养老生活、风险。
- 难例优先：贴近 5.5 分、海外 vs 中国、政策 vs 通用医疗、企业 PR vs 真实案例。
- 不要只标精选；负样本和边界样本才是校准的关键。

## 6. 标注完成后

把文件交给 AI，下一步会做：

1. 用金标跑当前评分 prompt，得到 precision/recall/F1；
2. 改五轴评分标准（影响面、证据强度、受众匹配、时效性、内容潜力）；
3. 再跑金标，比较改动前后；
4. 门槛只在校准后调整，不先拍脑袋改。

在完成这一步之前，不要继续加信源或改自动进化。
