# Intel Pipeline 优化计划

> 基于 2026-06-11 健康度评估，覆盖 INTERNAL_PRODUCT_ROADMAP.md DoD 项 + 评估新发现的工程改进项。
> 总原则：**先达 DoD，再提工程品质**。

---

## 一、全景视图

```
优先级   P0（本周）         P1（下周）         P2（第 3-4 周）     P3（持续）
        ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
DoD     │ D1 积压消化    │  │ D3 质量验收    │  │ D4 管道可靠性  │  │ D7 服务常驻    │
对应    │ D2 简报补全    │  │ D8 API Token  │  │ D6 CI 全覆盖  │  │              │
        │ D5 信源可用    │  │              │  │              │  │              │
        ├──────────────┤  ├──────────────┤  ├──────────────┤  ├──────────────┤
工程    │ E1 ruff 修复   │  │ E3 Score 校验 │  │ E5 API 分页   │  │ E7 Dashboard │
改进    │ E2 CI 扩展     │  │ E4 CORS 收紧  │  │ E6 日志规范化  │  │   模块化      │
        └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
```

---

## 二、P0 — 本周必做（6 月 12-13 日）

### T0.1 ruff 全量修复（E1）

**现状**：52 个 ruff 错误（29x F541 无占位符 f-string、21x F401 未使用 import、2x F841 未使用变量），全部可自动修复。

**操作**：
```bash
source .venv/bin/activate
ruff check engine/ --fix
# 验证
ruff check engine/  # 应输出 0 errors
pytest tests/ -q    # 应仍 194 passed
```

**涉及文件**：`engine/cli.py`、`engine/pipeline.py`、`engine/output/api.py`、`engine/output/notifier.py`、`engine/evolution/*.py`、`engine/fetcher/*.py` 等

**验收**：`ruff check engine/` 输出 0 errors，`pytest` 194 passed 不变。

**耗时**：5 分钟

---

### T0.2 CI ruff 覆盖扩展（E2）

**现状**：`.github/workflows/ci.yml` 的 ruff 只检查 `engine/ops engine/output/auth.py engine/filter/rule_prefilter.py`，遗漏了 engine 主体。

**修改**：`ci.yml` 中 ruff 行改为：
```yaml
- name: Ruff
  run: ruff check engine/
```

**验收**：本地 `ruff check engine/` 通过后，CI 应全绿。

**依赖**：T0.1 先完成。

**耗时**：2 分钟

---

### T0.3 待评分积压消化（D1 → 目标 < 50）

**现状**：`unscored_count = 176`

**操作**：
```bash
# 方案 A：CLI 循环（推荐，每轮约 5 分钟消化 50 条）
python -m engine.cli -d elderly-care ops digest-backlog --target 50

# 方案 B：手动循环
while true; do
  n=$(python -c "from engine.store import Store; print(Store().get_unscored_count('elderly-care'))")
  echo "unscored=$n"
  [ "$n" -lt 50 ] && break
  python -m engine.cli -d elderly-care pipe
done
```

**验收**：`python -m engine.cli -d elderly-care quality-metrics` 显示 `unscored_count < 50`

**耗时**：约 20-30 分钟（4-5 轮 pipe）

---

### T0.4 历史精选补简报（D2 → 目标 ≥ 80%）

**现状**：`headline` 非空的精选占比 22%（17/76）

**操作**：
```bash
# 先看有多少待补
python -m engine.cli -d elderly-care briefing-backfill --days 30 --dry-run

# 执行补全（每批 50 条，可多次运行）
python -m engine.cli -d elderly-care briefing-backfill --days 30 --limit 50
```

**验收**：
```bash
python -m engine.cli -d elderly-care quality-metrics
# briefing_coverage_pct ≥ 80%
```

**依赖**：T0.3 先清积压（否则补全会处理大量低分条目）。

**耗时**：10-15 分钟（取决于 LLM 速度）

---

### T0.5 信源可用性确认（D5 → 目标 < 3 失败）

**现状**：31/31 信源可用，但需确认自动降级机制正常。

**操作**：
```bash
python -m engine.cli -d elderly-care evolve lifecycle
# 检查是否有 critical/ineffective 状态的信源

python -m engine.cli -d elderly-care evolve sources --days 7
# 检查健康报告
```

**验收**：无 critical 状态信源；如有，手动确认后 `evolve restore <source_id>`。

**耗时**：5 分钟

---

## 三、P1 — 下周（6 月 16-20 日）

### T1.1 API 写操作 Token 保护（D8）

**现状**：`auth.py` 和 `config.py` 中 `api_token` 机制已实现，但 `.env` 中 `INTEL_API_TOKEN=` 为空。

**操作**：
1. 生成随机 Token：`python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. 写入 `.env`：`INTEL_API_TOKEN=<生成的值>`
3. Dashboard 前端需在 `localStorage` 存储 Token 并在 POST 请求中携带

**修改文件**：
- `.env` — 设置 Token
- `engine/output/templates/dashboard.html` — 反馈/信源管理操作携带 Authorization header

**验收**：
```bash
# 无 Token → 401
curl -X POST "http://localhost:8901/api/items/feedback?raw_id=1&domain=elderly-care&corrected_score=8"
# → {"detail":"需要 Authorization: Bearer <token>"}

# 有 Token → 200
curl -X POST -H "Authorization: Bearer <token>" \
  "http://localhost:8901/api/items/feedback?raw_id=1&domain=elderly-care&corrected_score=8"
```

**耗时**：2-3 小时

---

### T1.2 每周质量验收流程固化（D3）

**现状**：`quality-review` 命令已就绪，但未制度化。

**操作**：
1. 每周一执行：`python -m engine.cli -d elderly-care quality-review --take 20 --days 7`
2. 输出 Markdown 报告到 `data/reports/quality-elderly-care-YYYY-MM-DD.md`
3. 人工标注误报（报告中有 `[ ] 通过 / [ ] 误报 / [ ] 待观察` 勾选框）
4. 误报率 > 20% → 当周修改 `scoring.md` 或 `rule_prefilter.py` 后重跑 pipe

**改进项**：在 `quality-review` 输出末尾增加自动误报率计算提示：
```
验收方法：数出标记为「误报」的条目数，除以总条目数。
目标：误报率 < 20%（即 20 条中误报 ≤ 4 条）
```

**验收**：连续 2 周有 `data/reports/quality-*.md` 存档，误报率 < 20%。

**耗时**：每周 15 分钟人工验收

---

### T1.3 ScoredItem.score 范围校验（E3）

**现状**：`ScoredItem.score` 无 `Field(ge=0, le=10)` 约束。

**修改**：`engine/models.py`
```python
# 当前
score: float = 0.0

# 改为
score: float = Field(default=0.0, ge=0, le=10)
```

**验收**：`ScoredItem(score=11)` 抛出 ValidationError；现有测试全通过。

**耗时**：10 分钟

---

### T1.4 CORS 收紧（E4）

**现状**：`allow_origins=["*"]` 全放开。

**修改**：`engine/output/api.py`
```python
# 当前
allow_origins=["*"]

# 改为（按实际部署域名配置）
_allow_origins = ["http://localhost:8900", "http://localhost:8901", "http://127.0.0.1:8900", "http://127.0.0.1:8901"]
# 可通过环境变量 INTEL_CORS_ORIGINS 覆盖
```

**验收**：Dashboard 正常加载；跨域请求被拒绝。

**耗时**：30 分钟

---

### T1.5 规则预筛误杀审查

**操作**：
```bash
python -c "
from engine.store import Store
s = Store()
rows = s.conn.execute(
    \"SELECT title, reason FROM scored_items WHERE domain='elderly-care' AND category='rejected' ORDER BY created_at DESC LIMIT 20\"
).fetchall()
for r in rows:
    print(f'{r[\"reason\"][:30]:30s} | {r[\"title\"][:60]}')
"
```

人工审查 20 条被拒条目，确认无误杀。如有误杀，调整 `rule_prefilter.py` 的 `_OFF_TOPIC_TITLE_KEYWORDS`。

**验收**：误杀率 < 5%（20 条中 ≤ 1 条误杀）。

**耗时**：15 分钟

---

## 四、P2 — 第 3-4 周（6 月 23 日起）

### T2.1 管道可靠性验证（D4、D7）

**目标**：7 日 pipe 成功率 ≥ 95%。

**操作**：
1. 确保 scheduler 7×24 运行：`./scripts/start.sh && ./scripts/status.sh`
2. 每日检查：`python -m engine.cli -d elderly-care quality-metrics`（查看 `pipe_7d`）
3. 失败时查日志：`tail -50 data/logs/scheduler.log`

**增强**：`scripts/status.sh` 增加末次 pipe 时间和错误摘要：
```bash
python -c "
from engine.store import Store
s = Store()
r = s.get_last_pipe_run('elderly-care')
if r: print(f'末次 pipe: {r[\"created_at\"]} | 耗时 {r[\"duration_seconds\"]}s | 采集 {r[\"fetch_new\"]} | 错误 {r[\"fetch_errors\"]}')
"
```

**验收**：连续 7 天 `pipe_runs` 记录，成功率 ≥ 95%。

**耗时**：7 天观察 + 1 小时 status.sh 增强

---

### T2.2 CI 全覆盖（D6 增强）

**现状**：CI 已有 pytest + ruff（T0.2 扩展后），但可进一步增强。

**增强项**：
- 添加 `python -m engine.cli preflight` 检查（验证配置模板完整性）
- 添加 import 检查（`python -c "from engine.output.api import app"` 确保无导入错误）
- 可选：添加 `mypy` 类型检查（渐进式，先 `--ignore-missing-imports`）

**验收**：PR 合并前必须 CI 全绿。

**耗时**：2-3 小时

---

### T2.3 日志规范化（E6）

**现状**：日志使用一致（`logging.getLogger(__name__)`），但存在以下问题：
- `pipeline.py` 中 `score_stats` 变量赋值后未使用（ruff F841）
- 部分 `except Exception` 过于宽泛，应捕获具体异常
- 缺少结构化日志（JSON 格式），不便于生产环境聚合

**操作**：
1. 修复 F841（T0.1 已覆盖）
2. 关键路径细化异常捕获：
   - `pipeline.py` 采集阶段：`except (httpx.HTTPError, feedparser.FeedParserError) as e`
   - `notifier.py` 推送：`except httpx.HTTPError as e`
3. 可选：引入 `python-json-logger` 替代默认 formatter

**验收**：`ruff check engine/` 全绿；关键异常有明确错误类型。

**耗时**：2-3 小时

---

### T2.4 API 分页支持（E5）

**现状**：靠 `take` 参数截断，无分页机制。

**修改**：`engine/output/api.py` 的 `/api/items` 端点增加 `offset` 参数：
```python
@app.get("/api/items")
def get_items(
    ...,
    offset: int = Query(default=0, ge=0),
    ...
):
    ...
    return {
        "domain": domain,
        "mode": mode,
        "count": len(items),
        "total": total_count,  # 新增：总数
        "offset": offset,
        "has_more": offset + len(items) < total_count,
        "items": items,
        ...
    }
```

**验收**：`/api/items?offset=0&take=10` 和 `/api/items?offset=10&take=10` 返回不同数据。

**耗时**：2-3 小时

---

### T2.5 备份与恢复演练（D7 补充）

**操作**：
```bash
# 备份
./scripts/backup.sh

# 验证备份
ls -la data/backups/

# 恢复演练（在临时目录）
mkdir -p /tmp/intel-restore
cp data/backups/2026-06-XX/intel-elderly-care.db /tmp/intel-restore/
python -c "import sqlite3; conn = sqlite3.connect('/tmp/intel-restore/intel-elderly-care.db'); print(conn.execute('SELECT COUNT(*) FROM raw_items').fetchone())"
```

**验收**：备份 + 恢复演练 < 10 分钟；恢复后 DB 可读。

**耗时**：30 分钟

---

## 五、P3 — 持续改进

### T3.1 Dashboard 优化（E7，低优先级）

**现状**：单文件 ~1400 行 JS，功能完整但维护成本高。

**改进项**（按需）：
- Tailwind 构建化：用 `@tailwindcss/cli` 生成静态 CSS 替代 `tailwind.js` 运行时编译
- `alert()/confirm()` 替换为 toast/modal 组件
- 虚拟列表（`IntersectionObserver`）优化长列表性能
- 暗色模式

**不做**：框架重写（React/Vue）、模块化拆分（单文件够用）。

**耗时**：按需，每次 1-2 小时

---

### T3.2 推送重试机制

**现状**：`notifier.py` 推送失败仅日志记录，无重试。

**改进**：在 `send_webhook` 中增加 1 次重试（指数退避 2s）。

**耗时**：30 分钟

---

### T3.3 API 版本化

**现状**：端点无版本前缀。

**改进**：添加 `/api/v1/` 前缀，保留旧路径兼容（301 重定向）。

**不做**：现阶段内网使用，版本化收益低。仅在对外暴露时考虑。

---

## 六、验收检查清单（更新版）

```
P0 — 本周（6 月 12-13 日）
[x] E1  ruff check engine/ → 0 errors
[x] E2  CI ruff 覆盖全 engine/
[ ] D1  unscored_count < 50
[ ] D2  briefing_coverage ≥ 80%
[ ] D5  无 critical 信源

P1 — 下周（6 月 16-20 日）
[ ] D8  API POST 需 Token
[ ] D3  首次 quality-review 完成，误报率 < 20%
[ ] E3  ScoredItem.score 有范围校验
[ ] E4  CORS 收紧
[ ] 规则预筛误杀率 < 5%

P2 — 第 3-4 周（6 月 23 日起）
[ ] D4  7 日 pipe 成功率 ≥ 95%
[ ] D6  CI 全绿（pytest + ruff + preflight）
[ ] E5  API 分页支持
[ ] E6  日志规范化
[ ] 备份恢复演练通过

P3 — 持续
[ ] E7  Dashboard Tailwind 构建化
[ ] 推送重试机制

最终验收
[ ] 全部 P0-P2 勾选
[ ] 连续 2 周 quality-review 误报率 < 20%
[ ] 连续 7 天 pipe 成功率 ≥ 95%
```

---

## 七、耗时估算

| 阶段 | 开发耗时 | 运营耗时 |
|------|----------|----------|
| P0 本周 | 1 小时 | 30 分钟（pipe 跑积压） |
| P1 下周 | 4-6 小时 | 每周 15 分钟验收 |
| P2 第 3-4 周 | 6-8 小时 | 7 天观察 |
| P3 持续 | 按需 | — |
| **合计** | **~12-15 小时开发** | **2 周运营观察** |

---

## 八、与 INTERNAL_PRODUCT_ROADMAP.md 的关系

本计划是 ROADMAP 的**实施细化版**：
- ROADMAP 定义了 DoD 目标（D1-D8）
- 本计划补充了工程改进项（E1-E7），并给出了具体操作步骤和验收命令
- 两份文档应同步维护：DoD 达标后更新 ROADMAP 的"当前"列
