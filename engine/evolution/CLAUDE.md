[根目录](../../CLAUDE.md) > [engine](../) > **evolution**

# evolution — 自动进化模块

## 模块职责

基于历史采集与评分数据，自动分析信源质量、校准评分分布、扩展关键词、管理信源生命周期（产出率追踪与自动降级/恢复）。

## 入口与启动

- **CLI**：`intel evolve sources|scoring|keywords|all|lifecycle|restore <source_id>`
- **管道集成**：`pipeline.py` 在 `pipe` 完成后自动运行 lifecycle、keyword staging、scoring calibration

## 子模块职责

| 文件 | 职责 |
|---|---|
| `source_analyzer.py` | 信源质量统计（ineffective/dormant 检测），输出 Markdown 报告 |
| `scoring_calibrator.py` | 评分分布分析，生成调整建议 |
| `scoring_injector.py` | 将校准指令注入下次 `scoring.md` prompt |
| `keyword_expander.py` | 从高分配条目中挖掘新关键词 |
| `keyword_staging.py` | 暂存关键词建议，`pipe` 时自动 A/B 验证后合并或回滚 |
| `source_lifecycle.py` | 日产出率度量、`source_metrics` 表、自动降级/人工 confirm/restore |

## 数据流（pipe 后处理）

```
run_lifecycle_check()
  → record_daily_metrics → detect_degradation → apply_degradation (修改 sources.yaml enabled)

keyword_staging.check_and_apply()
  → 对比暂存关键词通过率 vs 历史平均 → 合并/回滚 keywords.yaml

scoring_injector.run_calibration_check()
  → 写入校准 JSON → 下次 score_items 注入 prompt
```

## 信源类型差异化策略

`models.py` 中 `SOURCE_TYPE_CONFIG` 定义各类信源最低产出率、观察期、是否自动禁用（policy/research 不自动禁用，media/hotlist 会）。

## 关键依赖与配置

- 读取 `Store` 的 `scored_items`、`source_metrics`
- 写入 `data/evolution/` 报告（各 analyzer 的 `save_*_report`）
- 修改 `domains/<name>/sources.yaml`（降级时设 `enabled: false`）
- 修改 `domains/<name>/keywords.yaml`（staging 通过后追加）

## 测试与质量

- `tests/test_evolution.py` — 覆盖六子模块（keyword_staging、scoring_calibrator、scoring_injector、source_lifecycle、source_analyzer、keyword_expander），使用 tmp_path fixture 隔离文件写入
- **缺口**：无端到端 `pipe` 后进化流程集成测试

## 常见问题 (FAQ)

**Q: 如何恢复被自动降级的信源？**  
A: `intel evolve restore <source_id>` 或 API `POST /api/sources/{id}/enable`。

**Q: 关键词 `--apply` 与默认 `--stage` 区别？**  
A: `--apply` 直接追加到 yaml；默认暂存后在下次 pipe 自动验证效果。

## 相关文件清单

```
engine/evolution/
├── source_analyzer.py
├── scoring_calibrator.py
├── scoring_injector.py
├── keyword_expander.py
├── keyword_staging.py
├── source_lifecycle.py
└── __init__.py
```

## 常见修改场景

| 场景 | 修改位置 |
|---|---|
| 调整信源降级阈值 | `models.py:SOURCE_TYPE_CONFIG` + `source_lifecycle.py` |
| 修改关键词 A/B 验证逻辑 | `keyword_staging.py` |
| 评分分布校准规则 | `scoring_calibrator.py` + `scoring_injector.py` |
| 手动分析信源质量 | `intel evolve sources` → `source_analyzer.py` |

## 变更记录 (Changelog)

- **2026-06-11**：补充 `test_evolution.py` 覆盖说明与常见修改场景
- **2026-06-10**：init-architect 初始化
