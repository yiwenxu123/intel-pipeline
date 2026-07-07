# Intel Pipeline 全面优化计划

## 概述

基于对项目全量代码的深度分析，识别出 22 个优化点，按优先级分为 4 个批次实施。本计划聚焦于**高价值、低风险**的改进，避免过度工程化。

---

## 当前状态分析

项目是一个可配置的行业情报引擎，核心流程为：采集(fetch) → 筛选(filter) → 日报(report) → 推送(notify)，支持自动进化（信源生命周期、评分校准、关键词扩展）。

**主要问题分类：**
- 架构层：Store 连接管理低效、全局可变状态线程不安全
- 安全层：API 鉴权薄弱、LLM 调用无重试
- 性能层：去重两次查询、LIKE 查询无索引、简报串行调用
- 质量层：CLI/pipeline SQL 不一致、YAML 正则修改脆弱
- 规范层：CI 用 pip 非 uv、配置默认值不一致、临时文件散落

---

## 批次一：架构与安全修复（高优先级）

### 1.1 Pipeline 共享 Store 实例

**文件：** `engine/pipeline.py`

**问题：** `run_full_pipeline()` 中 4 次创建/销毁 Store（采集、筛选、日报、推送各一次），每次都重新初始化 SQLite 连接和表结构。

**方案：** 将整个管道共享一个 Store 实例，通过参数传递。

```python
# 修改前（4次创建）
with Store() as store:  # 采集
    result.fetch = fetch_all(domain, store)
with Store() as store:  # 筛选
    ...
with Store() as store:  # 日报
    ...
with Store() as store:  # 推送
    ...

# 修改后（1次创建）
with Store() as store:
    result.fetch = fetch_all(domain, store)
    # 筛选阶段直接用同一个 store
    # 日报阶段直接用同一个 store
    # 推送阶段直接用同一个 store
```

**注意：** 需要调整各阶段的异常处理，确保一个阶段失败不会影响 store 的关闭。

### 1.2 LLM 客户端封装为类，消除全局可变状态

**文件：** `engine/filter/llm_client.py`

**问题：** 模块级全局变量 `_call_count/_input_tokens/_output_tokens` + `reset_usage()` 无锁保护，多线程下存在竞态条件。

**方案：** 封装为 `LLMUsageTracker` 类，提供线程安全的接口。

```python
class LLMUsageTracker:
    """线程安全的 LLM 用量追踪器。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._call_count = 0
        self._input_tokens = 0
        self._output_tokens = 0

    def reset(self):
        with self._lock:
            self._call_count = 0
            self._input_tokens = 0
            self._output_tokens = 0

    def record(self, input_tokens: int, output_tokens: int):
        with self._lock:
            self._call_count += 1
            self._input_tokens += input_tokens
            self._output_tokens += output_tokens

    def get_usage(self) -> dict:
        with self._lock:
            return {
                "calls": self._call_count,
                "input_tokens": self._input_tokens,
                "output_tokens": self._output_tokens,
                "total_tokens": self._input_tokens + self._output_tokens,
            }

# 模块级单例
usage_tracker = LLMUsageTracker()
```

**同步修改：** 所有调用 `reset_usage()` / `get_usage()` 的地方改为 `usage_tracker.reset()` / `usage_tracker.get_usage()`。

**涉及文件：**
- `engine/filter/llm_client.py` — 主要修改
- `engine/pipeline.py` — 调用处适配
- `engine/cli.py` — 调用处适配

### 1.3 评分统计封装为类

**文件：** `engine/filter/pipeline.py`

**问题：** `_score_stats` 是裸全局字典，`reset_score_stats()` 无锁。

**方案：** 类似 1.2，封装为 `ScoreStats` 类，或直接复用 `LLMUsageTracker` 模式。

### 1.4 LLM 调用增加重试机制

**文件：** `engine/filter/llm_client.py`

**问题：** `chat()` 异常时直接返回空字符串，临时网络错误导致数据丢失。

**方案：** 增加指数退避重试，最多 3 次。

```python
import time

_MAX_RETRIES = 3
_RETRY_DELAYS = [1, 3, 5]  # 秒

def chat(model: str, system: str, user: str, temperature: float = 0.3) -> str:
    """调用 LLM，返回文本响应。支持重试。"""
    client = get_client()
    last_error = None

    for attempt in range(_MAX_RETRIES):
        try:
            resp = client.chat.completions.create(...)
            # ... 追踪用量
            return resp.choices[0].message.content or ""
        except Exception as e:
            last_error = e
            if attempt < _MAX_RETRIES - 1:
                delay = _RETRY_DELAYS[attempt]
                logger.warning(f"LLM 调用失败（第{attempt+1}次），{delay}s 后重试: {e}")
                time.sleep(delay)
            else:
                logger.error(f"LLM 调用失败（已重试{_MAX_RETRIES}次）: {e}")

    return ""
```

### 1.5 API Token 空值时启动警告

**文件：** `engine/output/api.py`

**问题：** `INTEL_API_TOKEN` 为空时所有写操作无鉴权，但无任何提示。

**方案：** 在 `start_api()` 启动时打印警告日志。

```python
def start_api():
    if not settings.api_token:
        logger.warning("⚠️ INTEL_API_TOKEN 未配置，所有写操作无鉴权保护！建议在内网环境使用。")
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
```

---

## 批次二：代码质量与一致性（中优先级）

### 2.1 统一 CLI/pipeline 的待评分查询逻辑

**文件：** `engine/store.py`, `engine/pipeline.py`, `engine/cli.py`

**问题：** `pipeline.py` 的筛选查询包含日期容错（`published < '2020-01-01'`），但 `cli.py` 的 `filter` 命令缺少此逻辑，导致 CLI 和管道行为不一致。

**方案：** 在 Store 中新增 `get_unscored_items()` 方法，统一查询逻辑。

```python
# engine/store.py 新增方法
def get_unscored_items(self, domain: str, window_days: int = 7, limit: int = 50) -> list[RawItem]:
    """获取窗口期内未评分的条目（含日期容错）。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    rows = self.conn.execute(
        """SELECT r.* FROM raw_items r
           WHERE (
               (r.published >= ? AND r.published >= '2020-01-01')
               OR (r.published IS NULL AND r.fetched_at >= ?)
               OR (r.published < '2020-01-01' AND r.fetched_at >= ?)
           )
           AND r.id NOT IN (SELECT raw_id FROM scored_items WHERE domain = ?)
           ORDER BY COALESCE(r.published, r.fetched_at) DESC
           LIMIT ?""",
        (cutoff, cutoff, cutoff, domain, limit),
    ).fetchall()
    return [
        RawItem(
            source_id=r["source_id"], title=r["title"], url=r["url"],
            content=r["content"] or "", lang=r["lang"] or "zh",
            full_text=r["full_text"],
        )
        for r in rows
    ]
```

**同步修改：**
- `engine/pipeline.py` — 调用 `store.get_unscored_items()`
- `engine/cli.py` — 调用 `store.get_unscored_items()`

### 2.2 Store 去重优化：合并 exists + save_raw

**文件：** `engine/store.py`

**问题：** `fetch_all()` 中先调 `store.exists()` 再调 `store.save_raw()`，两次数据库查询。`save_raw()` 内部也有重复查询。

**方案：** 新增 `save_raw_if_new()` 方法，单次查询完成去重+插入。

```python
def save_raw_if_new(self, item: RawItem) -> tuple[int, bool]:
    """保存原始条目（去重）。返回 (id, is_new)。"""
    import hashlib
    h = hashlib.md5(item.url.encode()).hexdigest()
    with self._write_lock:
        existing = self.conn.execute("SELECT id FROM raw_items WHERE url_hash = ?", (h,)).fetchone()
        if existing:
            return existing["id"], False
        cur = self.conn.execute(
            """INSERT INTO raw_items (...) VALUES (...)""",
            (...),
        )
        self.conn.commit()
        return cur.lastrowid or 0, True
```

**同步修改：** `engine/fetcher/runner.py` 中的去重入库逻辑。

### 2.3 YAML 修改改用 pyyaml 完整读写

**文件：** `engine/evolution/source_lifecycle.py`

**问题：** `apply_degradation()` / `restore_source()` 等用正则修改 YAML，脆弱易出错。

**方案：** 使用 `yaml.safe_load` + `yaml.safe_dump` 完整读写。

```python
def apply_degradation(domain: str, degraded: list[dict]) -> list[str]:
    yaml_path = settings.project_root / "domains" / domain / "sources.yaml"
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    disabled_ids = []
    for source in data.get("sources", []):
        if source.get("id") in degraded_ids:
            if not source.get("enabled") is False:  # 未被手动禁用
                source["enabled"] = False
                source["_auto_degraded_at"] = datetime.now().strftime("%Y-%m-%d")
                disabled_ids.append(source["id"])

    if disabled_ids:
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return disabled_ids
```

**注意：** 需要检查 YAML 写入后的格式是否与现有格式兼容（缩进、注释等）。如果需要保留注释，考虑使用 `ruamel.yaml`。

### 2.4 SQL order_by 白名单校验

**文件：** `engine/store.py`

**问题：** `_query_items()` 的 `order_by` 参数通过 f-string 拼接进 SQL。

**方案：** 增加白名单校验。

```python
_VALID_ORDER_BY = frozenset({
    "s.score DESC", "s.score ASC",
    "s.created_at DESC", "s.created_at ASC",
    "COALESCE(r.published, r.fetched_at) DESC",
})

def _query_items(self, ..., order_by: str = "s.score DESC") -> list[dict]:
    if order_by not in _VALID_ORDER_BY:
        raise ValueError(f"Invalid order_by: {order_by}")
    ...
```

### 2.5 hashlib 提到模块顶部

**文件：** `engine/store.py`

**问题：** `hashlib` 在 `exists()` 和 `save_raw()` 中重复导入。

**方案：** 移到文件顶部 `import hashlib`。

---

## 批次三：性能优化（中优先级）

### 3.1 简报提炼并行化

**文件：** `engine/filter/briefing.py`

**问题：** `enrich_briefings()` 对精选条目逐条串行调用 LLM，评分阶段已并行但简报没有。

**方案：** 使用 `ThreadPoolExecutor` 并行处理简报提炼。

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def enrich_briefings(items, domain, store=None):
    ...
    selected_idx = [i for i, it in enumerate(items) if it.score >= 6.0]
    if not selected_idx:
        return items

    # 并行简报提炼
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_brief_one, items[idx], system): idx for idx in selected_idx}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                items[idx] = future.result()
            except Exception as e:
                logger.warning(f"简报提炼失败 [{items[idx].raw.title[:30]}]: {e}")

    return items
```

### 3.2 日期查询优化：增加日期索引

**文件：** `engine/store.py`

**问题：** `_record_daily_snapshot()` 和 `get_stats()` 使用 `LIKE '2024-01-01%'` 查询，无法利用索引。

**方案：** 在 `_init_tables()` 中为 `fetched_at` 和 `created_at` 增加日期索引，并将 LIKE 查询改为范围查询。

```sql
-- 新增索引
CREATE INDEX IF NOT EXISTS idx_raw_fetched_date ON raw_items(fetched_at);
CREATE INDEX IF NOT EXISTS idx_scored_created_date ON scored_items(domain, created_at);
```

```python
# LIKE 改范围查询
# 修改前
"WHERE fetched_at LIKE ?" (f"{date}%",)

# 修改后
"WHERE fetched_at >= ? AND fetched_at < ?" (f"{date}T00:00:00", f"{date}T23:59:59")
```

**涉及位置：**
- `engine/pipeline.py` 的 `_record_daily_snapshot()`
- `engine/store.py` 的 `get_stats()`

---

## 批次四：规范与清理（低优先级）

### 4.1 统一 .env.example 与 config.py 默认值

**文件：** `.env.example`, `engine/config.py`

**问题：**
- `INTEL_SCORE_WINDOW_DAYS`: .env.example=3, config.py=7
- `INTEL_API_HOST`: .env.example=127.0.0.1, config.py=0.0.0.0

**方案：** 以 config.py 为准（代码是实际运行的），更新 .env.example：
- `INTEL_SCORE_WINDOW_DAYS=7`
- `INTEL_API_HOST=0.0.0.0`

### 4.2 清理废弃配置

**文件：** `engine/config.py`, `.env.example`

**问题：** `llm_pre_filter_model` 和 `pre_filter_backlog_threshold` 已废弃。

**方案：**
- `config.py` 中添加 `# DEPRECATED` 注释，保留字段但标记废弃
- `.env.example` 中移除 `INTEL_PRE_FILTER_BACKLOG_THRESHOLD` 和 `INTEL_LLM_PRE_FILTER_MODEL`

### 4.3 CI 改用 uv

**文件：** `.github/workflows/ci.yml`

**方案：**
```yaml
- name: Install uv
  uses: astral-sh/setup-uv@v4
- name: Install dependencies
  run: uv sync --dev
- name: Ruff
  run: uv run ruff check engine/
- name: Pytest
  run: uv run pytest tests/ -q
```

### 4.4 清理根目录临时文件

**文件：** 项目根目录

**需清理的文件：**
- `dashboard-fixed-snapshot.yml`
- `dashboard-fixed.png`
- `dashboard-screenshot.png`
- `page-snapshot.yml`

**同步修改：** `.gitignore` 中添加：
```
# Playwright MCP snapshots
*-snapshot.yml
*.screenshot.png
```

### 4.5 测试 conftest 添加 LLM mock

**文件：** `tests/conftest.py`

**方案：** 添加 fixture mock 所有 LLM 调用，防止测试意外产生 API 费用。

```python
@pytest.fixture(autouse=True)
def mock_llm(monkeypatch):
    """Mock 所有 LLM 调用，防止测试产生 API 费用。"""
    def _mock_chat(model, system, user, temperature=0.3):
        return '[{"score":7.0,"category":"test","tags":[],"title":"测试","summary":"测试摘要","key_points":[],"reason":"测试","content_type":"news"}]'

    monkeypatch.setattr("engine.filter.llm_client.chat", _mock_chat)
```

---

## 假设与决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| YAML 修改方式 | 先用 pyyaml，如需保留注释再换 ruamel.yaml | 最小改动原则 |
| LLM 重试次数 | 3 次，延迟 1/3/5 秒 | 平衡可靠性与延迟 |
| Store 连接共享 | 单实例贯穿管道 | 减少连接开销，代码更简洁 |
| 日期查询优化 | 范围查询替代 LIKE | 兼容现有数据，无需迁移 |
| 废弃配置处理 | 保留字段+标记注释 | 向后兼容，不破坏现有 .env |

---

## 验证步骤

1. **批次一验证：**
   - 运行 `pytest tests/ -q` 确认无回归
   - 手动运行 `intel pipe` 确认管道正常
   - 检查日志确认 Store 只创建一次
   - 模拟 LLM 超时确认重试生效

2. **批次二验证：**
   - 运行 `intel filter` 和 `intel pipe` 对比结果一致性
   - 测试 YAML 修改后格式正确
   - 测试非法 order_by 参数被拒绝

3. **批次三验证：**
   - 对比简报提炼前后的执行时间
   - 确认日期范围查询结果与 LIKE 一致

4. **批次四验证：**
   - CI 流水线通过
   - 确认 .env.example 与 config.py 一致
   - 确认测试不产生 LLM 费用
